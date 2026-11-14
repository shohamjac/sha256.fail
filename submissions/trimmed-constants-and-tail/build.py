"""Builds a SHA-256 compression circuit for `sha256-compress-v1` with its own adders.

Same architecture as the baseline (`../example`): the state lives in `digest`, the message
schedule is expanded in place over `block` and rewound, and every carry and every AND is
cleared by measurement. What is different:

- The last two schedule words are never stored. W_62 and W_63 are each used once, by
  their own round, so their four terms are added straight into the state. That is four
  additions instead of seven (three to make the word, one to use it, three to unmake it).
- Constants are cheaper. Adding a constant costs one Toffoli per bit above its lowest set
  bit, and every register addition can take a carry-in of one for free. So each round
  adds K_t - j instead of K_t, with j chosen to give the most trailing zeros, and makes up
  the difference with carry-ins on the additions around it.
- Two additions in a row into the same register share their lowest bit (`add_two`): one
  AND there instead of two.
- Where the baseline adds into a register that holds a known constant, this copies the
  value with CNOTs and adds the constant instead.
- The final addition of the initial hash value is merged into the last round for H_0.
- Two fewer qubits. The top bit of an operand only ever flips the top bit of the target,
  so the temporary is 31 qubits, and the constant adder shares the 30 carry qubits.

The circuit is written out as Kickmix text, one gate per line, rather than through
Kickmix's arithmetic helpers. `check` (from the baseline) compares it against `hashlib`.

Usage, from this directory:

    uv run --project ../../sha256_verifier python build.py
"""

from __future__ import annotations

import importlib.util
import itertools
import pathlib

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


def rotr(x: int, n: int) -> int:
    return ((x >> n) | (x << (WORD - n))) & MASK


def bit(value: int, k: int) -> int:
    return (value >> k) & 1


def const_cost(value: int) -> int:
    """Toffolis `add_const` spends on `value`: one per bit above its lowest set bit, below the top."""
    value &= MASK
    if value == 0:
        return 0
    return max(0, 30 - ((value & -value).bit_length() - 1))


def sigma_sources(source: list[int], sigma, k: int) -> list[int]:
    """The qubits of `source` whose XOR is bit k of `sigma(source)`."""
    rotations, shift = sigma
    out = [source[(k + r) % WORD] for r in rotations]
    if shift is not None and k + shift < WORD:
        out.append(source[k + shift])
    return out


class Register:
    """An operand that is a 32-qubit register."""
    in_tmp = False

    def __init__(self, builder: 'Builder', qubits: list[int]) -> None:
        self.b, self.qubits = builder, qubits

    def begin(self) -> None: pass
    def end(self) -> None: pass
    def load(self, bits) -> None: pass
    def unload(self, bits) -> None: pass

    def qubit(self, k: int) -> int:
        return self.qubits[k]

    def top(self, target: int) -> None:
        self.b.cx(self.qubits[TOP], target)


class Linear:
    """An operand whose bit k is `flip[k]` XOR some qubits: Sigma, sigma, or Ch and Maj with
    two constant arguments. Bits 0..30 are copied into the temporary while it is added."""
    in_tmp = True

    def __init__(self, builder: 'Builder', sources, flip: int = 0) -> None:
        self.b, self.sources, self.flip = builder, sources, flip

    def begin(self) -> None: pass
    def end(self) -> None: pass

    def xor_bit(self, k: int, target: int) -> None:
        for s in self.sources(k):
            self.b.cx(s, target)
        if bit(self.flip, k):
            self.b.x(target)

    def load(self, bits) -> None:
        for k in bits:
            self.xor_bit(k, self.b.tmp[k])

    unload = load

    def qubit(self, k: int) -> int:
        return self.b.tmp[k]

    def top(self, target: int) -> None:
        self.xor_bit(TOP, target)


class AndXor:
    """An operand of the form `c ^ (u & v)` bit by bit, after `prepare` has been applied.

    Ch(e, f, g) = g ^ (e & (f ^ g)): prepare XORs g into f. Maj(a, b, c) = c ^ ((a ^ c) & (b ^ c)):
    prepare XORs c into a and b. `c` may be a constant. The ANDs go into the temporary and are
    cleared by measurement; `prepare` is its own inverse and must be in effect for both.
    """
    in_tmp = True

    def __init__(self, builder: 'Builder', u: list[int], v: list[int], c: list[int] | int,
                 prepare: list[list[int]]) -> None:
        self.b, self.u, self.v, self.c, self.prepare = builder, u, v, c, prepare

    def xor_c(self, k: int, target: int) -> None:
        if isinstance(self.c, int):
            if bit(self.c, k):
                self.b.x(target)
        else:
            self.b.cx(self.c[k], target)

    def begin(self) -> None:
        for register in self.prepare:
            for k in range(WORD):
                self.xor_c(k, register[k])

    end = begin

    def load(self, bits) -> None:
        for k in bits:
            self.b.ccx(self.u[k], self.v[k], self.b.tmp[k])
            self.xor_c(k, self.b.tmp[k])

    def unload(self, bits) -> None:
        for k in bits:
            self.xor_c(k, self.b.tmp[k])
            self.b.measure(self.b.tmp[k])
            self.b.fix_cz(self.u[k], self.v[k])

    def qubit(self, k: int) -> int:
        return self.b.tmp[k]

    def top(self, target: int) -> None:
        self.b.ccx(self.u[TOP], self.v[TOP], target)
        self.xor_c(TOP, target)


class Builder:
    """Emits the circuit as Kickmix text. A register is a list of 32 qubit indices, bit 0 first."""

    def __init__(self) -> None:
        self.ops: list[str] = []
        self.w = [list(range(WORD * j, WORD * (j + 1))) for j in range(16)]
        self.h = [list(range(512 + WORD * j, 512 + WORD * (j + 1))) for j in range(8)]
        self.tmp = list(range(768, 768 + 31))  # Bits 0..30 of whatever is being added.
        self.carry = list(range(799, 799 + 30))  # carry[i] holds the carry into bit i + 1.

    # ---- gates -------------------------------------------------------------------------

    def x(self, q: int) -> None:
        self.ops.append(f'X q{q}')

    def cx(self, c: int, t: int) -> None:
        self.ops.append(f'CX q{c} q{t}')

    def ccx(self, a: int, b: int, t: int) -> None:
        self.ops.append(f'CCX q{a} q{b} q{t}')

    def measure(self, q: int) -> None:
        """Measures `q` in the X basis into bit 0 and resets it. A phase fix-up must follow."""
        self.ops.append(f'HMR q{q} b0')

    def fix_z(self, q: int) -> None:
        self.ops.append(f'Z q{q} if b0')

    def fix_cz(self, a: int, b: int) -> None:
        self.ops.append(f'CZ q{a} q{b} if b0')

    def x_word(self, register: list[int], value: int = MASK) -> None:
        for k in range(WORD):
            if bit(value, k):
                self.x(register[k])

    def cx_word(self, source: list[int], target: list[int]) -> None:
        for s, t in zip(source, target):
            self.cx(s, t)

    # ---- operands ------------------------------------------------------------------------

    def reg(self, qubits: list[int]) -> Register:
        return Register(self, qubits)

    def sigma(self, source: list[int], sigma) -> Linear:
        return Linear(self, lambda k: sigma_sources(source, sigma, k))

    def select(self, source: list[int], mask: int, flip: int) -> Linear:
        """`(source & mask) ^ flip` for constants: Ch(e, f, g) = (e & (f ^ g)) ^ g and
        Maj(a, b, c) = (a & (b ^ c)) ^ (b & c) when two of the arguments are constants."""
        return Linear(self, lambda k: [source[k]] if bit(mask, k) else [], flip)

    def ch(self, e: list[int], f: list[int], g: list[int] | int) -> AndXor:
        return AndXor(self, e, f, g, [f])

    def maj(self, a: list[int], b: list[int], c: list[int] | int) -> AndXor:
        return AndXor(self, a, b, c, [a, b])

    # ---- adders ------------------------------------------------------------------------

    def add(self, a: list[int], b: list[int], top, *, carry_in=0) -> None:
        """`b += operand + carry_in` modulo 2^n for n = len(b), with n - 1 Toffolis.

        Args:
            a: n - 1 qubits holding the low bits of the operand. Used as controls and restored.
            b: The n-qubit target.
            top: Called with `b[-1]` to XOR the top bit of the operand into it.
            carry_in: 0, 1, or `('q', qubit)` for a carry held in a qubit, which is left
                unchanged. A constant 1 costs nothing: the first carry is an OR, not an AND.

        Uses `carry[0 .. n-3]`. The carry into the top bit goes straight into the target.
        """
        n, c = len(b), self.carry
        quantum = isinstance(carry_in, tuple)

        def holder(i: int) -> int:  # The qubit holding the carry into bit i.
            return carry_in[1] if i == 0 else c[i - 1]

        def up(i: int) -> None:  # carry' = carry ^ ((a ^ carry) & (b ^ carry))
            p = holder(i)
            self.cx(p, a[i]), self.cx(p, b[i])
            self.ccx(a[i], b[i], c[i])
            self.cx(p, c[i])

        def down(i: int) -> None:  # Clear the carry by measurement and finish bit i.
            p = holder(i)
            self.cx(p, c[i])
            self.measure(c[i])
            self.fix_cz(a[i], b[i])
            self.cx(p, a[i]), self.cx(a[i], b[i])

        if quantum:
            up(0)
        elif carry_in:  # The carry into bit 1 is a_0 OR b_0.
            self.x(a[0]), self.x(b[0])
            self.ccx(a[0], b[0], c[0])
            self.x(c[0]), self.x(a[0]), self.x(b[0])
        else:
            self.ccx(a[0], b[0], c[0])
        for i in range(1, n - 2):
            up(i)
        p = holder(n - 2)
        self.cx(p, a[n - 2]), self.cx(p, b[n - 2])
        self.ccx(a[n - 2], b[n - 2], b[n - 1])
        self.cx(p, b[n - 1])
        self.cx(p, a[n - 2]), self.cx(a[n - 2], b[n - 2])
        top(b[n - 1])
        for i in range(n - 3, 0, -1):
            down(i)
        if quantum:
            down(0)
        else:
            self.measure(c[0])
            self.fix_cz(a[0], b[0])
            if carry_in:  # a OR b = a ^ b ^ (a & b)
                self.fix_z(a[0]), self.fix_z(b[0])
            self.cx(a[0], b[0])
            if carry_in:
                self.x(b[0])

    def add_const(self, value: int, b: list[int]) -> None:
        """`b += value` for a constant, with one Toffoli per bit above its lowest set bit.

        Below the lowest set bit j nothing changes. Bit j flips, and its old value is the
        carry into bit j + 1, so `b[j]` itself serves as that carry until the end.
        """
        value &= MASK
        if value == 0:
            return
        j = (value & -value).bit_length() - 1
        if j == TOP:
            self.x(b[TOP])
            return
        c = self.carry

        def holder(i: int) -> int:  # The qubit holding the carry into bit i.
            return b[j] if i == j + 1 else c[i - 1]

        for i in range(j + 1, 31):
            p, k = holder(i), bit(value, i)
            self.cx(p, b[i])
            if k:
                self.x(p)  # p is now (constant bit ^ carry).
            self.ccx(p, b[i], c[i] if i < 30 else b[TOP])
            if k:
                self.x(p)
            self.cx(p, c[i] if i < 30 else b[TOP])
            if i == 30 and k:
                self.x(b[30])
        if j == 30:
            self.cx(b[30], b[TOP])
        if bit(value, TOP):
            self.x(b[TOP])
        for i in range(29, j, -1):
            p, k = holder(i), bit(value, i)
            self.cx(p, c[i])
            self.measure(c[i])
            self.fix_cz(p, b[i])
            if k:
                self.fix_z(b[i])
                self.x(b[i])
        self.x(b[j])

    def add_one(self, op, target: list[int], carry_in: int = 0) -> None:
        """`target += op + carry_in`: 31 Toffolis, plus the operand's own ANDs."""
        op.begin()
        op.load(range(TOP))
        self.add([op.qubit(k) for k in range(TOP)], target, op.top, carry_in=carry_in)
        op.unload(range(TOP))
        op.end()

    def add_two(self, first, second, target: list[int], carry_in: int = 0) -> None:
        """`target += first + second + 2 * carry_in` with 61 Toffolis instead of 62.

        Two additions in a row each compute a carry out of bit 0, but the two carries are
        never both set: together they are Maj(target_0, first_0, second_0). So bit 0 is done
        once, with one AND, and the two additions run on bits 1..31, the second taking that
        majority as its carry-in. `first` must not be an `AndXor`.
        """
        m, spare, r0 = self.carry[29], self.carry[28], target[0]
        upper = target[1:]

        second.begin()
        second.load([0])
        second.end()
        q2 = second.qubit(0)
        q1 = spare if first.in_tmp else first.qubit(0)

        def toggle_q1() -> None:
            if first.in_tmp:
                first.xor_bit(0, spare)

        toggle_q1()
        self.cx(r0, q1), self.cx(r0, q2)
        self.ccx(q1, q2, m)
        self.cx(r0, m)  # m = Maj(r0, q1, q2)
        self.cx(r0, q1), self.cx(r0, q2)
        self.cx(q1, r0), self.cx(q2, r0)  # Bit 0 of the sum; final.
        toggle_q1()

        first.begin()
        first.load(range(1, TOP))
        self.add([first.qubit(k) for k in range(1, TOP)], upper, first.top, carry_in=carry_in)
        first.unload(range(1, TOP))
        first.end()

        second.begin()
        second.load(range(1, TOP))
        self.add([second.qubit(k) for k in range(1, TOP)], upper, second.top, carry_in=('q', m))
        second.unload(range(1, TOP))
        second.end()

        toggle_q1()
        self.cx(q1, r0), self.cx(q2, r0)  # Back to the old bit 0, to clear m.
        self.cx(r0, q1), self.cx(r0, q2)
        self.cx(r0, m)
        self.measure(m)
        self.fix_cz(q1, q2)
        self.cx(r0, q1), self.cx(r0, q2)
        self.cx(q1, r0), self.cx(q2, r0)
        toggle_q1()

        second.begin()
        second.unload([0])
        second.end()

    def run(self, units, modes, target: list[int], *, const: int = 0) -> None:
        """Performs a planned group of additions into `target`; see `plans`. The constant, if
        any, is added after the first unit."""
        for i, (unit, mode) in enumerate(zip(units, modes)):
            if len(unit) == 1:
                self.add_one(unit[0], target, mode)
            elif isinstance(mode, tuple):  # A pair done as two separate additions.
                self.add_one(unit[0], target, mode[0])
                self.add_one(unit[1], target, mode[1])
            else:
                self.add_two(unit[0], unit[1], target, mode)
            if i == 0:
                self.add_const(const, target)

    # ---- rounds --------------------------------------------------------------------------

    def message_units(self, t: int) -> list[tuple]:
        """The additions that put W_t into the state, as units for `plans`."""
        if t < 62:
            return [(self.reg(self.w[t % 16]),)]
        # W_62 and W_63 are not stored: add their four terms. The window holds W_46 .. W_61.
        return [(self.reg(self.w[(t - 16) % 16]), self.sigma(self.w[(t - 15) % 16], SMALL_SIGMA0)),
                (self.reg(self.w[(t - 7) % 16]), self.sigma(self.w[(t - 2) % 16], SMALL_SIGMA1))]

    def round(self, t: int, state: list[list[int]]) -> list[list[int]]:
        """One full round in place, for t >= 4. Returns the registers now holding a..h.

        T1 = h + Sigma1(e) + Ch(e,f,g) + K_t + W_t goes into h, is added to d, and then
        h += Sigma0(a) + Maj(a,b,c). Carry-ins worth x before `d += h`, and worth y on
        `d += h` and again after it, stand in for x + y of K_t.

        In round 63 the initial hash value is folded in, so that h ends as H_0 and d as H_4.
        That takes two constants, split in one of two ways, whichever is cheaper: K_63 + IV_0
        into h before `d += h` and IV_4 - IV_0 into d; or nothing into h before `d += h`,
        K_63 + IV_4 into d and K_63 + IV_0 into h at the end.
        """
        a, b, c, d, e, f, g, h = state
        message = self.message_units(t)
        if len(message[0]) == 1:  # One register: pair it with Ch, and add Sigma1 alone.
            before = [(self.sigma(e, BIG_SIGMA1),), (message[0][0], self.ch(e, f, g))]
        else:
            before = [(self.sigma(e, BIG_SIGMA1), self.ch(e, f, g)), *message]
        after = [(self.sigma(a, BIG_SIGMA0), self.maj(a, b, c))]

        last = t == 63
        options = []
        for (bm, x, bc), y, (am, z, ac) in itertools.product(plans(before), range(2), plans(after)):
            if not last:
                if z != y:
                    continue  # d and h must receive the same total.
                splits = [(K[t] - x - z, 0, 0)]
            else:
                splits = [(K[t] + IV[0] - x - z, IV[4] - IV[0] + z - y, 0),
                          (0, K[t] + IV[4] - x - y, K[t] + IV[0] - x - z)]
            for k_before, k_d, k_after in splits:
                cost = const_cost(k_before) + const_cost(k_d) + const_cost(k_after) + bc + ac
                options.append((cost, x + y + z, y, k_before, k_d, k_after, bm, am))
        _, _, y, k_before, k_d, k_after, before_modes, after_modes = min(options, key=lambda o: o[:2])

        self.run(before, before_modes, h, const=k_before)
        self.add_one(self.reg(h), d, y)
        self.add_const(k_d, d)
        self.run(after, after_modes, h)
        self.add_const(k_after, h)
        return [h, a, b, c, d, e, f, g]

    def early_round(self, t: int, state, *, h_const: int, d_const: int, ch, maj) -> None:
        """Rounds 1 to 3, where the registers serving as h and d are still known constants.

        Both start at zero. h is loaded with Sigma1(e) by CNOTs and then given its constant;
        d is a CNOT copy of T1 plus its constant. `ch` and `maj` are this round's operands.
        """
        a, _, _, d, e, _, _, h = state
        before = [(self.reg(self.w[t]), ch)]
        after = [(self.sigma(a, BIG_SIGMA0), maj)]
        options = []
        for (bm, x, bc), (am, z, ac) in itertools.product(plans(before), plans(after)):
            k_h, k_d = h_const - x - z, d_const + z
            options.append((const_cost(k_h) + const_cost(k_d) + bc + ac, x + z, k_h, k_d, bm, am))
        _, _, k_h, k_d, before_modes, after_modes = min(options, key=lambda o: o[:2])

        for k in range(WORD):
            for s in sigma_sources(e, BIG_SIGMA1, k):
                self.cx(s, h[k])
        self.add_const(k_h, h)
        self.run(before, before_modes, h)
        self.cx_word(h, d)
        self.add_const(k_d, d)
        self.run(after, after_modes, h)

    def schedule(self, t: int, *, undo: bool = False) -> None:
        """Turns W_(t-16) into W_t in place, or back again.

        W_t = W_(t-16) + sigma0(W_(t-15)) + W_(t-7) + sigma1(W_(t-2)); word W_s is `w[s % 16]`.
        Subtracting is adding to the complement: b - x = not(not b + x).
        """
        target = self.w[t % 16]
        if undo:
            self.x_word(target)
        self.add_one(self.sigma(self.w[(t - 15) % 16], SMALL_SIGMA0), target)
        self.add_two(self.reg(self.w[(t - 7) % 16]), self.sigma(self.w[(t - 2) % 16], SMALL_SIGMA1), target)
        if undo:
            self.x_word(target)

    def build(self) -> km.Circuit:
        A, B, C, D, E, F, G, H = IV
        r = self.h
        t1 = (H + (rotr(E, 6) ^ rotr(E, 11) ^ rotr(E, 25)) + ((E & F) ^ (~E & G)) + K[0]) & MASK
        t2 = ((rotr(A, 2) ^ rotr(A, 13) ^ rotr(A, 22)) + ((A & B) ^ (A & C) ^ (B & C))) & MASK

        # Round 0: every input but W_0 is a constant, so e_1 = W_0 + (D + t1) and
        # a_1 = W_0 + (t1 + t2) = e_1 + (t2 - D). Copy, then add whichever constant is cheaper.
        self.cx_word(self.w[0], r[3])
        self.add_const(D + t1, r[3])
        if const_cost(t2 - D) < const_cost(t1 + t2):
            self.cx_word(r[3], r[7])
            self.add_const(t2 - D, r[7])
        else:
            self.cx_word(self.w[0], r[7])
            self.add_const(t1 + t2, r[7])

        # Rounds 1 to 3. The registers that will hold constants are left at zero and the
        # constants are used directly; K_1..K_3 are folded into the constant given to h.
        self.early_round(1, [r[7], A, B, r[2], r[3], E, F, r[6]], h_const=G + K[1], d_const=C,
                         ch=self.select(r[3], E ^ F, F), maj=self.select(r[7], A ^ B, A & B))
        self.early_round(2, [r[6], r[7], A, r[1], r[2], r[3], E, r[5]], h_const=F + K[2], d_const=B,
                         ch=self.ch(r[2], r[3], E), maj=self.maj(r[6], r[7], A))
        self.early_round(3, [r[5], r[6], r[7], r[0], r[1], r[2], r[3], r[4]], h_const=E + K[3], d_const=A,
                         ch=self.ch(r[1], r[2], r[3]), maj=self.maj(r[5], r[6], r[7]))
        state = [r[4], r[5], r[6], r[7], r[0], r[1], r[2], r[3]]

        for t in range(4, 64):
            if 16 <= t < 62:
                self.schedule(t)
            state = self.round(t, state)
        assert all(now is start for now, start in zip(state, r)), 'state registers did not line up'

        # Feed-forward. Round 63 already added IV_0 and IV_4.
        for j in (1, 2, 3, 5, 6, 7):
            self.add_const(IV[j], r[j])

        for t in reversed(range(16, 62)):  # Restore the block.
            self.schedule(t, undo=True)

        header = []
        for index, (name, start, size) in enumerate((('block', 0, 512), ('digest', 512, 256))):
            header += [f'APPEND_TO_REGISTER q{q} r{index}' for q in range(start, start + size)]
            header.append(f'REGISTER r{index} "{name}"')
        return km.Circuit('\n'.join(header + self.ops))


def plans(units: list[tuple]) -> list[tuple[list, int, int]]:
    """Every way to hand out carry-ins over a group of additions into one register.

    A unit is one operand or a pair of operands. A single addition takes a carry-in of 0 or
    1. A pair done by `add_two` takes 0 or 2; done as two separate additions, which costs
    one more Toffoli, it can take exactly 1.

    Returns:
        `(modes, total carry-in, extra Toffolis)` for each choice. A mode is the carry-in of
        a single addition or of `add_two`, or a tuple of two carry-ins for a split pair.
    """
    choices = [[(0, 0, 0), (1, 1, 0)] if len(unit) == 1 else [(0, 0, 0), (1, 2, 0), ((1, 0), 1, 1)]
               for unit in units]
    return [([mode for mode, _, _ in combo], sum(v for _, v, _ in combo), sum(c for _, _, c in combo))
            for combo in itertools.product(*choices)]


def main() -> None:
    circuit = Builder().build()
    baseline.check(circuit)
    path = pathlib.Path(__file__).with_name('circuit.kmb')
    circuit.to_file(path, format='kmb')
    stats = circuit.operation_statistics()
    print(f'Wrote {path.name}: {circuit.num_qubits} qubits, {stats.num_toffoli_like} Toffolis, '
          f'{len(circuit)} operations, {path.stat().st_size} bytes. Matches hashlib on 1024 messages.')


if __name__ == '__main__':
    main()
