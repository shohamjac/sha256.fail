"""Builds a SHA-256 compression circuit for `sha256-compress-v1` on 768 qubits: no scratch.

The contract's registers are 512 qubits of `block` and 256 of `digest`, so 768 is the floor.
Nothing here is measured: the circuit is X, CNOT and Toffoli gates only. Every piece that
normally takes scratch qubits is done in place:

- Additions keep their carries in the wires of the number being added (Takahashi, Tani and
  Kunihiro's adder): `2n - 3` Toffolis mod 2^n instead of `n - 1`, and no carry qubits.
- Sigma and sigma operands are linear and invertible, so the register is turned into
  Sigma(register) by CNOTs, added, and turned back.
- Ch and Maj are computed onto one of their own inputs, added, and undone.
- A constant has no wires to keep carries in. It is added as signed binary digits: for a
  digit at bit j, add some unrelated register y to the bits from j up and then add its
  complement, which nets -2^j (or +2^j with carry-ins of one), whatever y holds.

Usage, from this directory:

    uv run --project ../../sha256_verifier python build.py
"""

from __future__ import annotations

import importlib.util
import itertools
import pathlib
import random

import kickmix as km

_spec = importlib.util.spec_from_file_location(
    'baseline_build', pathlib.Path(__file__).parent.parent / 'example' / 'build.py')
baseline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(baseline)

WORD, K, IV = baseline.WORD, baseline.K, baseline.IV
MASK = (1 << WORD) - 1
TOP = WORD - 1

BIG_SIGMA0, BIG_SIGMA1 = baseline.BIG_SIGMA0, baseline.BIG_SIGMA1
SMALL_SIGMA0, SMALL_SIGMA1 = baseline.SMALL_SIGMA0, baseline.SMALL_SIGMA1


# ---- constants as signed digits ------------------------------------------------------------


def adder_cost(width: int) -> int:
    """Toffolis of one in-place addition of `width` bits, top carry dropped."""
    return max(0, 2 * width - 3)


def digit_cost(position: int) -> int:
    """Toffolis to add +-2^position: two additions on the bits from `position` up."""
    return 2 * adder_cost(WORD - position)


def signed_digits(value: int) -> tuple[int, list[tuple[int, int]]]:
    """The cheapest way to write `value` mod 2^32 as a sum of +-2^j.

    Returns:
        `(cost, [(j, sign), ...])`. A digit at a high bit is cheap, since its additions are
        narrow, so this is not always the form with the fewest digits.
    """
    value &= MASK
    best: dict[int, tuple[int, list[tuple[int, int]]]] = {0: (0, [])}
    for j in range(WORD):
        following: dict[int, tuple[int, list[tuple[int, int]]]] = {}

        def offer(carry: int, cost: int, digits: list[tuple[int, int]]) -> None:
            if carry not in following or cost < following[carry][0]:
                following[carry] = (cost, digits)

        for carry, (cost, digits) in best.items():
            v = (value >> j & 1) + carry
            if v != 1:
                offer(v >> 1, cost, digits)
            else:
                offer(0, cost + digit_cost(j), digits + [(j, +1)])
                offer(1, cost + digit_cost(j), digits + [(j, -1)])
        best = following
    return min(best.values(), key=lambda entry: entry[0])  # A carry out of the top is dropped.


# ---- linear maps in place ---------------------------------------------------------------


def in_place(sigma) -> tuple[list[tuple[int, int]], list[int]]:
    """CNOTs that turn a register x into sigma(x) in place.

    Returns:
        `(program, place)`: `program` is a list of `(control, target)` bit positions, and
        afterwards bit k of sigma(x) is on the wire that held bit `place[k]` of x. Running
        `program` backwards restores x.
    """
    rotations, shift = sigma
    rows = []
    for k in range(WORD):
        mask = 0
        for r in rotations:
            mask ^= 1 << ((k + r) % WORD)
        if shift is not None and k + shift < WORD:
            mask ^= 1 << (k + shift)
        rows.append(mask)

    # Gauss-Jordan elimination takes the rows of sigma to unit vectors. Each row operation is
    # a CNOT, so the same operations backwards take the wires of x to the rows of sigma.
    steps: list[tuple[int, int]] = []
    column_of: dict[int, int] = {}
    for column in range(WORD):
        pivot = next(s for s in range(WORD) if s not in column_of and rows[s] >> column & 1)
        column_of[pivot] = column
        for s in range(WORD):
            if s != pivot and rows[s] >> column & 1:
                rows[s] ^= rows[pivot]
                steps.append((pivot, s))
    program = [(column_of[p], column_of[s]) for p, s in reversed(steps)]
    return program, [column_of[s] for s in range(WORD)]


LINEAR = {name: in_place(sigma) for name, sigma in (
    ('S0', BIG_SIGMA0), ('S1', BIG_SIGMA1), ('s0', SMALL_SIGMA0), ('s1', SMALL_SIGMA1))}


# ---- the builder ----------------------------------------------------------------------------


class Builder:
    """Collects gates. A register is a list of 32 qubit indices, bit 0 first."""

    def __init__(self) -> None:
        self.gates: list[tuple] = []
        self.w = [list(range(WORD * j, WORD * (j + 1))) for j in range(16)]
        self.h = [list(range(512 + WORD * j, 512 + WORD * (j + 1))) for j in range(8)]

    # ---- gates -------------------------------------------------------------------------

    def x(self, q: int) -> None:
        self.gates.append((q,))

    def cx(self, c: int, t: int) -> None:
        self.gates.append((c, t))

    def ccx(self, a: int, b: int, t: int) -> None:
        self.gates.append((a, b, t))

    def x_word(self, register: list[int], value: int = MASK) -> None:
        for k, q in enumerate(register):
            if value >> k & 1:
                self.x(q)

    # ---- addition ----------------------------------------------------------------------

    def _first_carry(self, a0: int, b0: int, target: int, carry_in: int) -> None:
        """`target ^= carry out of bit 0`: a0 AND b0, or a0 OR b0 with a carry-in of one."""
        if carry_in:
            self.x(a0), self.x(b0)
        self.ccx(a0, b0, target)
        if carry_in:
            self.x(a0), self.x(b0), self.x(target)

    def add(self, a: list[int], b: list[int], carry_in: int = 0) -> None:
        """`b += a + carry_in` mod 2^len(b), with no other qubits.

        The carry into bit i + 1 is XORed into wire a[i + 1], which then holds a ^ carry;
        with b[i] holding a ^ b, the next carry is a ^ (a ^ carry)(a ^ b). The carry into
        the top bit goes straight into the top of `b`. `a` may be one bit shorter than `b`:
        then the caller adds its own top bit. `2 * len(b) - 3` Toffolis.
        """
        m = len(b)
        assert len(a) in (m, m - 1) and not set(a) & set(b)
        if m == 1:
            if a:
                self.cx(a[0], b[0])
            if carry_in:
                self.x(b[0])
            return
        for i in range(1, len(a)):
            self.cx(a[i], b[i])
        for i in range(m - 3, 0, -1):
            self.cx(a[i], a[i + 1])

        def carry(i: int, target: int) -> None:
            if i == 0:
                self._first_carry(a[0], b[0], target, carry_in)
            else:
                self.ccx(a[i], b[i], target)

        for i in range(m - 2):
            carry(i, a[i + 1])
        carry(m - 2, b[m - 1])
        for i in range(m - 2, 0, -1):
            self.cx(a[i], b[i])
            carry(i - 1, a[i])
        for i in range(1, m - 2):
            self.cx(a[i], a[i + 1])
        for i in range(m - 1):
            self.cx(a[i], b[i])
        if m > 2:
            self.cx(a[m - 2], b[m - 1])
        if carry_in:
            self.x(b[0])

    def add_linear(self, name: str, source: list[int], target: list[int], carry_in: int = 0) -> None:
        """`target += sigma(source) + carry_in` for one of the four sigma functions."""
        program, place = LINEAR[name]
        for c, t in program:
            self.cx(source[c], source[t])
        self.add([source[p] for p in place], target, carry_in)
        for c, t in reversed(program):
            self.cx(source[c], source[t])

    def add_ch(self, e: list[int], f: list[int], g: list[int], target: list[int], carry_in: int = 0) -> None:
        """`target += Ch(e, f, g) + carry_in`. Ch = g ^ (e & (f ^ g)) is computed onto g."""
        for k in range(WORD):
            self.cx(g[k], f[k])
        for k in range(TOP):
            self.ccx(e[k], f[k], g[k])
        self.ccx(e[TOP], f[TOP], target[TOP])  # The top bit only flips the top bit.
        self.cx(g[TOP], target[TOP])
        self.add(g[:TOP], target, carry_in)
        for k in range(TOP):
            self.ccx(e[k], f[k], g[k])
        for k in range(WORD):
            self.cx(g[k], f[k])

    def add_maj(self, a: list[int], b: list[int], c: list[int], target: list[int], carry_in: int = 0) -> None:
        """`target += Maj(a, b, c) + carry_in`. Maj = c ^ ((a ^ c) & (b ^ c)) is computed onto c."""
        for k in range(WORD):
            self.cx(c[k], a[k]), self.cx(c[k], b[k])
        for k in range(TOP):
            self.ccx(a[k], b[k], c[k])
        self.ccx(a[TOP], b[TOP], target[TOP])
        self.cx(c[TOP], target[TOP])
        self.add(c[:TOP], target, carry_in)
        for k in range(TOP):
            self.ccx(a[k], b[k], c[k])
        for k in range(WORD):
            self.cx(c[k], a[k]), self.cx(c[k], b[k])

    def add_const(self, value: int, target: list[int], borrowed: list[int]) -> None:
        """`target += value` for a constant, using `borrowed` only as somewhere to keep carries.

        For each signed digit +-2^j: add `borrowed` to the bits from j up, complement it,
        add it again, and complement it back. y + ~y is all ones, which is -1, so this
        subtracts 2^j; with a carry-in of one on both additions it adds 2^j instead.
        """
        for j, sign in signed_digits(value)[1]:
            if j == TOP:
                self.x(target[TOP])
                continue
            carry_in = 1 if sign > 0 else 0
            for _ in range(2):
                self.add(borrowed[j:], target[j:], carry_in)
                for q in borrowed[j:]:
                    self.x(q)

    # ---- rounds and schedule -----------------------------------------------------------

    def message(self, t: int, target: list[int], carry_ins: list[int]) -> None:
        """Adds W_t to `target`. `carry_ins` is consumed, one entry per addition."""
        if t < 62:
            self.add(self.w[t % 16], target, carry_ins.pop())
            return
        # W_62 and W_63 are not stored: add their four terms. The window holds W_46 .. W_61.
        self.add(self.w[(t - 16) % 16], target, carry_ins.pop())
        self.add_linear('s0', self.w[(t - 15) % 16], target, carry_ins.pop())
        self.add(self.w[(t - 7) % 16], target, carry_ins.pop())
        self.add_linear('s1', self.w[(t - 2) % 16], target, carry_ins.pop())

    def round(self, t: int, state: list[list[int]], *, offset: int = 0, last: bool = False) -> list[list[int]]:
        """One round in place. Returns the registers now holding a..h.

        T1 = h + Sigma1(e) + Ch(e,f,g) + K_t + W_t goes into h, is added to d, and then
        h += Sigma0(a) + Maj(a,b,c). Carry-ins of one on the additions are free, so the
        constant actually added is K_t less the carry-ins handed out, whichever is cheapest.
        `offset` is a part of K_t that h already holds.

        In the last round the initial hash value is folded in, so that h ends as H_0 and d
        as H_4. That takes two constants, split in one of two ways: K_63 + IV_0 into h
        before `d += h` and IV_4 - IV_0 into d; or nothing into h before `d += h`,
        K_63 + IV_4 into d and K_63 + IV_0 into h at the end.
        """
        a, b, c, d, e, f, g, h = state
        before = 2 + (1 if t < 62 else 4)  # Additions into h before `d += h`.
        k = K[t] - offset
        options = []
        for x, y, z in itertools.product(range(before + 1), range(2), range(3)):
            if not last:
                if z != y:
                    continue  # d and h must receive the same total.
                splits = [(k - x - z, 0, 0)]
            else:
                splits = [(k + IV[0] - x - z, IV[4] - IV[0] + z - y, 0),
                          (0, k + IV[4] - x - y, k + IV[0] - x - z)]
            for split in splits:
                options.append((sum(signed_digits(part)[0] for part in split), x + y + z, x, y, z, split))
        _, _, x, y, z, (k_before, k_d, k_after) = min(options)
        carry_ins = [1] * x + [0] * (before - x)

        self.add_linear('S1', e, h, carry_ins.pop())
        self.add_ch(e, f, g, h, carry_ins.pop())
        self.message(t, h, carry_ins)
        self.add_const(k_before, h, b)
        self.add(h, d, y)
        self.add_const(k_d, d, b)
        self.add_linear('S0', a, h, int(z > 0))
        self.add_maj(a, b, c, h, int(z > 1))
        self.add_const(k_after, h, b)
        return [h, a, b, c, d, e, f, g]

    def add_computed(self, compute, scratch: list[int], target: list[int]) -> None:
        """`target += value`, where `compute()` writes the value into the zero register
        `scratch`. Its gates are then run backwards to clear `scratch` again."""
        start = len(self.gates)
        compute()
        computed = self.gates[start:]
        self.add(scratch, target)
        self.gates += reversed(computed)

    def first_rounds(self) -> list[list[int]]:
        """Rounds 0 to 3, where part of the state is still a known constant.

        A register that would hold a constant is left at zero and the constant is used
        directly. The registers that receive the new a and e start at zero, so one constant
        can be written into each with X gates before the first addition. A zero register
        also serves as the place to compute Ch or Maj when one argument is a constant.
        """
        A, B, C, D, E, F, G, H = IV
        r, w = self.h, self.w
        t1 = (H + (rotr(E, 6) ^ rotr(E, 11) ^ rotr(E, 25)) + ((E & F) ^ (~E & G)) + K[0]) & MASK
        t2 = ((rotr(A, 2) ^ rotr(A, 13) ^ rotr(A, 22)) + ((A & B) ^ (A & C) ^ (B & C))) & MASK

        # Round 0: every input but W_0 is a constant. e_1 = W_0 + (D + t1) goes into r[3] and
        # a_1 = W_0 + (t1 + t2) into r[7].
        self.x_word(r[3], D + t1), self.add(w[0], r[3])
        self.x_word(r[7], t1 + t2), self.add(w[0], r[7])

        def select(source: list[int], mask: int, flip: int):
            """Writes `(source & mask) ^ flip` into r[0]: Ch or Maj with two constant arguments."""
            def compute() -> None:
                for k in range(WORD):
                    if mask >> k & 1:
                        self.cx(source[k], r[0][k])
                self.x_word(r[0], flip)
            return compute

        # Round 1: a = r[7], b = A, c = B, d = C, e = r[3], f = E, g = F, h = G.
        self.x_word(r[6], G + K[1])
        self.add_linear('S1', r[3], r[6])
        self.add_computed(select(r[3], E ^ F, F), r[0], r[6])
        self.add(w[1], r[6])
        self.x_word(r[2], C), self.add(r[6], r[2])
        self.add_linear('S0', r[7], r[6])
        self.add_computed(select(r[7], A ^ B, A & B), r[0], r[6])

        # Round 2: a = r[6], b = r[7], c = A, d = B, e = r[2], f = r[3], g = E, h = F.
        def ch_constant_g() -> None:  # Ch(e, f, E) = E ^ (e & (f ^ E)).
            self.x_word(r[3], E)
            for k in range(WORD):
                self.ccx(r[2][k], r[3][k], r[0][k])
            self.x_word(r[3], E)
            self.x_word(r[0], E)

        def maj_constant_c() -> None:  # Maj(a, b, A) = (a & b) ^ (A & (a ^ b)).
            for k in range(WORD):
                self.ccx(r[6][k], r[7][k], r[0][k])
                if A >> k & 1:
                    self.cx(r[6][k], r[0][k]), self.cx(r[7][k], r[0][k])

        self.x_word(r[5], F + K[2])
        self.add_linear('S1', r[2], r[5])
        self.add_computed(ch_constant_g, r[0], r[5])
        self.add(w[2], r[5])
        self.x_word(r[1], B), self.add(r[5], r[1])
        self.add_linear('S0', r[6], r[5])
        self.add_computed(maj_constant_c, r[0], r[5])

        # Round 3: a = r[5], b = r[6], c = r[7], d = A, e = r[1], f = r[2], g = r[3], h = E.
        self.x_word(r[4], E + K[3])
        self.add_linear('S1', r[1], r[4])
        self.add_ch(r[1], r[2], r[3], r[4])
        self.add(w[3], r[4])
        # r[3] is next used as h, in round 4, and only added to. While r[0] is still zero,
        # use it to give r[3] the round constant K_4 with a plain addition.
        self.add_computed(lambda: self.x_word(r[0], K[4]), r[0], r[3])
        self.x_word(r[0], A), self.add(r[4], r[0])
        self.add_linear('S0', r[5], r[4])
        self.add_maj(r[5], r[6], r[7], r[4])
        return [r[4], r[5], r[6], r[7], r[0], r[1], r[2], r[3]]

    def schedule(self, t: int, *, undo: bool = False) -> None:
        """Turns W_(t-16) into W_t in place, or back again.

        W_t = W_(t-16) + sigma0(W_(t-15)) + W_(t-7) + sigma1(W_(t-2)); word W_s is `w[s % 16]`.
        Subtracting is adding to the complement: b - x = not(not b + x).
        """
        target = self.w[t % 16]
        if undo:
            self.x_word(target)
        self.add_linear('s0', self.w[(t - 15) % 16], target)
        self.add(self.w[(t - 7) % 16], target)
        self.add_linear('s1', self.w[(t - 2) % 16], target)
        if undo:
            self.x_word(target)

    def build(self) -> None:
        state = self.first_rounds()
        for t in range(4, 64):
            if 16 <= t < 62:
                self.schedule(t)
            state = self.round(t, state, offset=K[4] if t == 4 else 0, last=t == 63)
        assert all(now is start for now, start in zip(state, self.h)), 'state registers did not line up'
        for j in (1, 2, 3, 5, 6, 7):  # Feed-forward. Round 63 already added IV_0 and IV_4.
            self.add_const(IV[j], self.h[j], self.h[(j + 1) % 8])
        for t in reversed(range(16, 62)):  # Restore the block.
            self.schedule(t, undo=True)

    # ---- output and self-test ------------------------------------------------------------

    @property
    def toffolis(self) -> int:
        return sum(len(gate) == 3 for gate in self.gates)

    def circuit(self) -> km.Circuit:
        names = {1: 'X', 2: 'CX', 3: 'CCX'}
        lines = []
        for index, (name, start, size) in enumerate((('block', 0, 512), ('digest', 512, 256))):
            lines += [f'APPEND_TO_REGISTER q{q} r{index}' for q in range(start, start + size)]
            lines.append(f'REGISTER r{index} "{name}"')
        lines += [names[len(gate)] + ''.join(f' q{q}' for q in gate) for gate in self.gates]
        return km.Circuit('\n'.join(lines))

    def self_test(self, shots: int = 64) -> None:
        """Runs the gates on `shots` random blocks at once and compares with a plain SHA-256."""
        rng = random.Random(1)
        ones = (1 << shots) - 1
        blocks = [[rng.getrandbits(WORD) for _ in range(16)] for _ in range(shots)]
        wires = [0] * 768
        for shot, block in enumerate(blocks):
            for j, word in enumerate(block):
                for k in range(WORD):
                    wires[self.w[j][k]] |= (word >> k & 1) << shot
        start = list(wires)
        for gate in self.gates:
            if len(gate) == 3:
                wires[gate[2]] ^= wires[gate[0]] & wires[gate[1]]
            elif len(gate) == 2:
                wires[gate[1]] ^= wires[gate[0]]
            else:
                wires[gate[0]] ^= ones
        assert wires[:512] == start[:512], 'block not restored'
        for shot, block in enumerate(blocks):
            want = reference(block)
            got = [sum((wires[self.h[j][k]] >> shot & 1) << k for k in range(WORD)) for j in range(8)]
            assert got == want, f'wrong digest on shot {shot}'


def rotr(x: int, n: int) -> int:
    return ((x >> n) | (x << (WORD - n))) & MASK


def reference(block: list[int]) -> list[int]:
    """SHA-256 compression of 16 words from the standard initial value."""
    w = list(block)
    for t in range(16, 64):
        s0 = rotr(w[t - 15], 7) ^ rotr(w[t - 15], 18) ^ (w[t - 15] >> 3)
        s1 = rotr(w[t - 2], 17) ^ rotr(w[t - 2], 19) ^ (w[t - 2] >> 10)
        w.append((w[t - 16] + s0 + w[t - 7] + s1) & MASK)
    a, b, c, d, e, f, g, h = IV
    for t in range(64):
        t1 = (h + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + K[t] + w[t]) & MASK
        t2 = ((rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) & MASK
        a, b, c, d, e, f, g, h = (t1 + t2) & MASK, a, b, c, (d + t1) & MASK, e, f, g
    return [(x + y) & MASK for x, y in zip(IV, (a, b, c, d, e, f, g, h))]


def main() -> None:
    builder = Builder()
    builder.build()
    builder.self_test()
    circuit = builder.circuit()
    baseline.check(circuit)
    path = pathlib.Path(__file__).with_name('circuit.kmb')
    circuit.to_file(path, format='kmb')
    stats = circuit.operation_statistics()
    print(f'Wrote {path.name}: {circuit.num_qubits} qubits, {stats.num_toffoli_like} Toffolis, '
          f'{len(circuit)} operations, {path.stat().st_size} bytes. Matches hashlib on 1024 messages.')


if __name__ == '__main__':
    main()
