"""Builds a low-Toffoli phase oracle for the problem `bitcoin-mining-v1`.

    |extranonce, nonce>  ->  (-1)^f |extranonce, nonce>

Written for the fewest Toffolis, with no regard for qubits: it uses every qubit the problem
allows. The contract is sha256_verifier/docs/bitcoin-mining-v1.md.

Two ideas carry it.

- **A carry that is kept costs nothing to undo.** The oracle computes the hash, flips the
  phase, and then has to undo the hash. Undoing an addition normally means subtracting,
  which computes every carry a second time. If the carries of the addition are left in
  qubits of their own, the addition is undone by CNOTs and measurements alone. So one
  spare qubit saves one Toffoli, and the circuit keeps carries (and the ANDs of Ch and Maj)
  until its qubits run out. What does not fit is computed twice, as in the baseline.
- **Classical inputs stay classical.** Only 80 input bits are qubits. Sums of classical
  words are worked out on classical bits, which costs nothing, and reach the qubits as one
  addend. Ch and Maj with classical arguments need no AND. The first nine rounds of the
  header's first block see no qubit at all.

Smaller things:

- Two additions in a row into one register share their lowest bit, and a constant gives up
  to three of its units to free carry-ins so that it ends in more zeros. Both are from
  `../trimmed-constants-and-tail`.
- The last compression computes only H_5, H_6 and H_7. At an easy exponent the target is
  zero under H_5, or under H_5 and H_6, and the rounds that serve only those words are
  put under a classical condition, so they are not executed in those shots.
- The comparison is a borrow chain whose last AND is never computed: its phase is a CZ.

The circuit is a list of steps for the forward half. The backward half is that list
reversed, with every "compute an AND into a clean qubit" swapped for "measure that qubit
away and fix the phase", and the other way round. Nothing else is written for it.

`check` (from the baseline) compares the circuit against `hashlib`.

Usage, from this directory:

    uv run --project ../../sha256_verifier python build.py [qubits]

`qubits` is the most the circuit may use, 65,536 when left out. Fewer qubits keep fewer
carries: the count goes up by one Toffoli for every qubit taken away.
"""

from __future__ import annotations

import heapq
import importlib.util
import io
import itertools
import pathlib
import sys

import kickmix as km

try:
    from compression import zstd  # Python 3.14 and later.
except ImportError:
    from backports import zstd

_HERE = pathlib.Path(__file__).parent
_spec = importlib.util.spec_from_file_location(
    'bitcoin_baseline_build', _HERE.parent / 'bitcoin-mining-baseline' / 'build.py')
reference = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reference)

WORD, K, IV = reference.WORD, reference.K, reference.IV
PAD256, PAD640 = reference.PAD256, reference.PAD640
BIG_SIGMA0, BIG_SIGMA1 = reference.BIG_SIGMA0, reference.BIG_SIGMA1
SMALL_SIGMA0, SMALL_SIGMA1 = reference.SMALL_SIGMA0, reference.SMALL_SIGMA1
MIN_EXPONENT, MAX_EXPONENT = reference.MIN_EXPONENT, reference.MAX_EXPONENT
TOP = WORD - 1
MAX_QUBITS = 65_536

# A classical bit is ZERO, ONE, or the index of a classical bit of the circuit.
ZERO, ONE = -1, -2

# (name, size, is quantum), in the order the contract fixes.
REGISTERS = (('extranonce', 48, True), ('nonce', 32, True), ('midstate', 256, False),
             ('tail', 464, False), ('version', 32, False), ('prev_hash', 256, False),
             ('time', 32, False), ('bits', 32, False), ('mask', 96, False))


class C(tuple):
    """A classical word: 32 classical bits, bit 0 first. A quantum word is a list of qubits."""


def const(value: int) -> C:
    return C(ONE if (value >> k) & 1 else ZERO for k in range(WORD))


def sigma_positions(sigma, k: int) -> list[int]:
    """The bit positions of x whose XOR is bit k of sigma(x)."""
    rotations, shift = sigma
    out = [(k + r) % WORD for r in rotations]
    if shift is not None and k + shift < WORD:
        out.append(k + shift)
    return out


class Reg:
    """An addend held in a register."""

    def __init__(self, qubits: list[int]) -> None:
        self.qubits = qubits


class Lin:
    """An addend whose bit k is a classical bit XOR some qubits, each qubit optionally under
    a classical condition. `bits[k]` is `(terms, flip)` with terms `(qubit, condition)`."""

    def __init__(self, bits: list[tuple[list[tuple[int, int]], int]]) -> None:
        self.bits = bits


class AndXor:
    """An addend of the form `c ^ (u & v)` bit by bit, once `prepare` has been applied.

    Ch(e, f, g) = g ^ (e & (f ^ g)) and Maj(a, b, c) = c ^ ((a ^ c) & (b ^ c)). `prepare` is a
    list of self-inverse steps; `c` is a quantum or a classical word.
    """

    def __init__(self, prepare: list[str], u: list[int], v: list[int], c) -> None:
        self.prepare, self.u, self.v, self.c = prepare, u, v, c


class Builder:
    """Emits the forward half as a list of steps and writes both halves out as Kickmix text.

    A step is a line of text that is its own inverse (X and CX, with or without a classical
    condition), `('A', u, v, t)` for an AND computed into the clean qubit t, `('D', u, v, t)`
    for that AND measured away, or `('L', text)` for operations on classical bits, which
    are not undone.
    """

    def __init__(self, keep: int) -> None:
        self.ops: list = []
        self.keep_left = keep
        self.kept = 0
        self.next_qubit = 80
        self.free_qubits: list[int] = []
        self.bit_base: dict[str, int] = {}
        bit = 0
        for name, size, quantum in REGISTERS:
            if not quantum:
                self.bit_base[name] = bit
                bit += size
        self.measured = bit  # Every measurement goes into this bit and is used at once.
        self.next_bit = bit + 1
        self.ands = 0  # ANDs computed in the forward half.
        self.erased = 0  # ANDs measured away in the forward half; the backward half computes them.
        self.parts: list[tuple[str, int, int]] = []

    # ---- qubits ----------------------------------------------------------------------------

    def alloc(self) -> int:
        if self.free_qubits:
            return heapq.heappop(self.free_qubits)
        self.next_qubit += 1
        return self.next_qubit - 1

    def alloc_word(self, n: int = WORD) -> list[int]:
        return [self.alloc() for _ in range(n)]

    def free(self, qubits) -> None:
        for q in qubits:
            heapq.heappush(self.free_qubits, q)

    def take(self, n: int) -> bool:
        """Whether n more ANDs may be kept in qubits of their own."""
        if n <= self.keep_left:
            self.keep_left -= n
            self.kept += n
            return True
        return False

    # ---- steps -----------------------------------------------------------------------------

    def x(self, q: int) -> None:
        self.ops.append(f'X q{q}')

    def xc(self, q: int, bit: int) -> None:
        """X under a classical bit."""
        if bit == ONE:
            self.ops.append(f'X q{q}')
        elif bit != ZERO:
            self.ops.append(f'X q{q} if b{bit}')

    def cx(self, c: int, t: int) -> None:
        self.ops.append(f'CX q{c} q{t}')

    def cxc(self, c: int, t: int, bit: int) -> None:
        """CX under a classical bit."""
        if bit == ONE:
            self.ops.append(f'CX q{c} q{t}')
        elif bit != ZERO:
            self.ops.append(f'CX q{c} q{t} if b{bit}')

    def begin(self, bit: int | None) -> None:
        """Opens a stretch that runs only when a classical bit is set."""
        if bit is not None:
            self.ops.append(('P', bit))

    def end(self, bit: int | None) -> None:
        if bit is not None:
            self.ops.append(('Q', bit))

    def and_(self, u: int, v: int) -> int:
        t = self.alloc()
        self.ops.append(('A', u, v, t))
        self.ands += 1
        return t

    def unand(self, u: int, v: int, t: int) -> None:
        self.ops.append(('D', u, v, t))
        self.erased += 1
        heapq.heappush(self.free_qubits, t)

    # ---- classical bits ----------------------------------------------------------------------

    def new_bit(self) -> int:
        self.next_bit += 1
        return self.next_bit - 1

    def classical(self, text: str) -> None:
        self.ops.append(('L', text))

    def c_not(self, x: int) -> int:
        if x < 0:
            return ONE if x == ZERO else ZERO
        t = self.new_bit()
        self.classical(f'BIT_INVERT b{t}\nBIT_INVERT b{t} if b{x}')
        return t

    def c_xor(self, *xs: int) -> int:
        flip, odd = 0, {}
        for x in xs:
            if x == ONE:
                flip ^= 1
            elif x != ZERO:
                odd[x] = not odd.get(x, False)
        bits = [x for x, on in odd.items() if on]
        if not bits:
            return ONE if flip else ZERO
        if len(bits) == 1 and not flip:
            return bits[0]
        t = self.new_bit()
        lines = [f'BIT_INVERT b{t} if b{x}' for x in bits]
        if flip:
            lines.append(f'BIT_INVERT b{t}')
        self.classical('\n'.join(lines))
        return t

    def c_and(self, x: int, y: int) -> int:
        if x == ZERO or y == ZERO:
            return ZERO
        if x == ONE or x == y:
            return y
        if y == ONE:
            return x
        t = self.new_bit()
        self.classical(f'PUSH_CONDITION if b{x}\nBIT_INVERT b{t} if b{y}\nPOP_CONDITION')
        return t

    def c_maj(self, x: int, y: int, z: int) -> int:
        """xy ^ z(x ^ y)."""
        constants = [v for v in (x, y, z) if v < 0]
        if constants:
            others = [v for v in (x, y, z) if v >= 0]
            if len(constants) >= 2:
                if constants[0] == constants[1]:
                    return constants[0]
                return others[0] if others else constants[2]
            if constants[0] == ZERO:
                return self.c_and(*others)
            return self.c_not(self.c_and(self.c_not(others[0]), self.c_not(others[1])))
        p = self.c_xor(x, y)
        if p == ZERO:
            return x
        t = self.new_bit()
        self.classical(f'PUSH_CONDITION if b{x}\nBIT_INVERT b{t} if b{y}\nPOP_CONDITION\n'
                       f'PUSH_CONDITION if b{z}\nBIT_INVERT b{t} if b{p}\nPOP_CONDITION')
        return t

    def cw_add(self, x: C, y: C, carry: int = ZERO) -> C:
        out = []
        for k in range(WORD):
            out.append(self.c_xor(x[k], y[k], carry))
            if k < TOP:
                carry = self.c_maj(x[k], y[k], carry)
        return C(out)

    def cw_sub(self, x: C, y: C) -> C:
        return self.cw_add(x, C(self.c_not(b) for b in y), ONE)

    def cw_sigma(self, x: C, sigma) -> C:
        return C(self.c_xor(*(x[p] for p in sigma_positions(sigma, k))) for k in range(WORD))

    def cw_ch(self, e: C, f: C, g: C) -> C:
        return C(self.c_xor(g[k], self.c_and(e[k], self.c_xor(f[k], g[k]))) for k in range(WORD))

    def cw_maj(self, a: C, b: C, c: C) -> C:
        return C(self.c_maj(a[k], b[k], c[k]) for k in range(WORD))

    def input_word(self, register: str, offset: int) -> C:
        base = self.bit_base[register] + offset
        return C(range(base, base + WORD))

    # ---- additions ---------------------------------------------------------------------------

    def add(self, b: list[int], a: list[int], keep: bool, carry_in=None) -> None:
        """`b += a + carry_in` modulo 2^n for n = len(b), with n - 1 ANDs. `a` is used as
        controls and restored.

        Going up, bit i leaves a_i and b_i XORed with the carry into bit i and computes the
        carry into bit i + 1. Going down, each bit is finished. Without `keep` the carries
        are measured away on the way down; with it they stay, one qubit each.

        `carry_in` is None, 'one', or a qubit holding the carry, which is left alone. A constant
        one costs nothing: the first carry is then an OR instead of an AND.
        """
        top = len(b) - 1
        carries = []
        for i in range(top):
            p = carries[i - 1] if i else carry_in
            if p is None:
                t = self.and_(a[0], b[0])
            elif p == 'one':
                self.x(a[0]), self.x(b[0])
                t = self.and_(a[0], b[0])
                self.x(t), self.x(a[0]), self.x(b[0])
            else:
                self.cx(p, a[i]), self.cx(p, b[i])
                t = self.and_(a[i], b[i])
                self.cx(p, t)
            carries.append(t)
        self.cx(carries[top - 1], b[top]), self.cx(a[top], b[top])
        for i in range(top - 1, -1, -1):
            p, t = (carries[i - 1] if i else carry_in), carries[i]
            if p is None:
                if not keep:
                    self.unand(a[0], b[0], t)
                self.cx(a[0], b[0])
            elif p == 'one':
                if not keep:
                    self.x(a[0]), self.x(b[0]), self.x(t)
                    self.unand(a[0], b[0], t)
                    self.x(a[0]), self.x(b[0])
                self.cx(a[0], b[0]), self.x(b[0])
            else:
                if not keep:
                    self.cx(p, t)
                    self.unand(a[i], b[i], t)
                self.cx(p, a[i]), self.cx(a[i], b[i])

    def add_classical(self, b: list[int], value: C) -> None:
        """`b += value` for a classical word, with one AND per bit above its lowest bit that
        is not known to be zero, the top bit excepted.

        Below that bit j nothing changes. The carry into bit j + 1 is the old b_j when
        value_j is the constant one, and a copy of b_j under value_j otherwise. Above it,
        carry' = carry ^ ((b ^ carry) & (value ^ carry)), and value ^ carry is the carry
        qubit with an X under the classical bit.
        """
        j = next((k for k in range(WORD) if value[k] != ZERO), None)
        if j is None:
            return
        if j == TOP:
            self.xc(b[TOP], value[TOP])
            return
        keep = self.take(TOP - 1 - j)
        if value[j] == ONE:
            first = b[j]
        else:
            first = self.alloc()
            self.cxc(b[j], first, value[j])
        carries = {j + 1: first}
        for i in range(j + 1, TOP):
            p = carries[i]
            self.cx(p, b[i])
            self.xc(p, value[i])
            t = self.and_(p, b[i])
            self.xc(p, value[i])
            self.cx(p, t)
            carries[i + 1] = t
        self.cx(carries[TOP], b[TOP])
        self.xc(b[TOP], value[TOP])
        for i in range(TOP - 1, j, -1):
            p, t = carries[i], carries[i + 1]
            if not keep:
                self.cx(p, t)
                self.xc(p, value[i])
                self.unand(p, b[i], t)
                self.xc(p, value[i])
            self.xc(b[i], value[i])
        if value[j] != ONE:
            self.cxc(b[j], first, value[j])
            self.free([first])
        self.xc(b[j], value[j])

    def load(self, operand: Lin, target: list[int]) -> None:
        """`target ^= operand`. Its own inverse."""
        for k, (terms, flip) in enumerate(operand.bits):
            for qubit, condition in terms:
                self.cxc(qubit, target[k], condition)
            self.xc(target[k], flip)

    def and_word(self, operand: AndXor) -> list[int]:
        """32 clean qubits set to the operand. `prepare` must be in effect."""
        t = [self.and_(u, v) for u, v in zip(operand.u, operand.v)]
        self.xor_c(operand, t)
        return t

    def xor_c(self, operand: AndXor, t: list[int]) -> None:
        for k in range(WORD):
            if isinstance(operand.c, C):
                self.xc(t[k], operand.c[k])
            else:
                self.cx(operand.c[k], t[k])

    def open(self, operand):
        """Puts the operand on 32 qubits. Returns them and the function that takes it away."""
        if isinstance(operand, Reg):
            return operand.qubits, lambda: None
        if isinstance(operand, Lin):
            tmp = self.alloc_word()
            self.load(operand, tmp)

            def close() -> None:
                self.load(operand, tmp)
                self.free(tmp)
            return tmp, close
        keep = self.take(WORD)
        self.ops.extend(operand.prepare)
        t = self.and_word(operand)

        def close() -> None:
            if not keep:
                self.xor_c(operand, t)
                for u, v, q in zip(operand.u, operand.v, t):
                    self.unand(u, v, q)
            self.ops.extend(operand.prepare)
        return t, close

    def add_operand(self, target: list[int], operand, carry: bool = False) -> None:
        """`target += operand + carry`."""
        qubits, close = self.open(operand)
        self.add(target, qubits, self.take(TOP), 'one' if carry else None)
        close()

    def add_pair(self, target: list[int], first, second, carry: bool = False) -> None:
        """`target += first + second + 2 * carry` with 61 ANDs instead of 62.

        Two additions in a row each compute a carry out of bit 0, but the two carries are
        never both set: together they are Maj(target_0, first_0, second_0). So bit 0 is done
        once, with one AND, and the two additions run on bits 1 to 31, the second taking
        that majority as its carry-in. `first` must not be an `AndXor`: it is put on its
        qubits before `second` is prepared.
        """
        a1, close1 = self.open(first)
        a2, close2 = self.open(second)
        keep = self.take(1)
        r0, q1, q2 = target[0], a1[0], a2[0]
        self.cx(r0, q1), self.cx(r0, q2)
        m = self.and_(q1, q2)
        self.cx(r0, m)  # m = Maj(r0, q1, q2)
        self.cx(r0, q1), self.cx(r0, q2)
        self.cx(q1, r0), self.cx(q2, r0)  # Bit 0 of the sum; final.
        self.add(target[1:], a1[1:], self.take(TOP - 1), 'one' if carry else None)
        self.add(target[1:], a2[1:], self.take(TOP - 1), m)
        if not keep:  # Back to the old bit 0, to clear m.
            self.cx(q1, r0), self.cx(q2, r0)
            self.cx(r0, q1), self.cx(r0, q2)
            self.cx(r0, m)
            self.unand(q1, q2, m)
            self.cx(r0, q1), self.cx(r0, q2)
            self.cx(q1, r0), self.cx(q2, r0)
        close2()
        close1()

    def materialize(self, operand) -> list[int]:
        """A new register holding the operand. The ANDs of an `AndXor` made this way sit in
        a register the circuit needs anyway, so undoing them is free without keeping more."""
        if isinstance(operand, AndXor):
            self.ops.extend(operand.prepare)
            t = self.and_word(operand)
            self.ops.extend(operand.prepare)
            return t
        register = self.alloc_word()
        if isinstance(operand, Reg):
            for s, t in zip(operand.qubits, register):
                self.cx(s, t)
        else:
            self.load(operand, register)
        return register

    def accumulate(self, base: list[int] | None, operands: list, lump: C) -> list[int]:
        """`base + operands + lump` in `base`, or in a new register when there is none.

        The addends go in pairs where they can. When the classical part is a constant, some
        of it is handed out as carry-ins, which are free, to leave a constant with more
        trailing zeros: a constant costs one AND per bit above its lowest set bit.
        """
        operands = list(operands)
        if base is None:
            if not operands:
                base = self.alloc_word()
                for k in range(WORD):
                    self.xc(base[k], lump[k])
                return base
            operands.sort(key=lambda o: 0 if isinstance(o, AndXor) else 1)
            base = self.materialize(operands.pop(0))
        plain = [o for o in operands if not isinstance(o, AndXor)]
        units = []
        for operand in operands:
            if isinstance(operand, AndXor):
                units.append((plain.pop(), operand) if plain else (operand,))
        while len(plain) >= 2:
            units.append((plain.pop(), plain.pop()))
        if plain:
            units.append((plain.pop(),))

        carries: tuple[int, ...] = ()
        if all(bit < 0 for bit in lump):
            value = sum(1 << k for k in range(WORD) if lump[k] == ONE)
            best = None
            for chosen in itertools.chain.from_iterable(
                    itertools.combinations(range(len(units)), n) for n in range(len(units) + 1)):
                rest = (value - sum(len(units[i]) for i in chosen)) % (1 << WORD)
                cost = max(0, TOP - 1 - ((rest & -rest).bit_length() - 1)) if rest else 0
                if best is None or cost < best[0]:
                    best = cost, chosen, rest
            _, carries, value = best
            lump = const(value)
        for i, unit in enumerate(units):
            if len(unit) == 1:
                self.add_operand(base, unit[0], i in carries)
            else:
                self.add_pair(base, *unit, i in carries)
        self.add_classical(base, lump)
        return base

    # ---- SHA-256 -----------------------------------------------------------------------------

    def sigma(self, x: list[int], sigma) -> Lin:
        return Lin([([(x[p], ONE) for p in sigma_positions(sigma, k)], ZERO) for k in range(WORD)])

    def ch(self, e, f, g):
        """Ch(e, f, g) = g ^ (e & (f ^ g)) as a classical word or an addend. e is the newest
        of the three, so it is quantum whenever one of them is."""
        if isinstance(e, C):
            assert isinstance(f, C) and isinstance(g, C)
            return self.cw_ch(e, f, g)
        if isinstance(f, C):
            assert isinstance(g, C)
            return Lin([([(e[k], self.c_xor(f[k], g[k]))], g[k]) for k in range(WORD)])
        if isinstance(g, C):
            prepare = [f'X q{f[k]} if b{g[k]}' if g[k] >= 0 else f'X q{f[k]}'
                       for k in range(WORD) if g[k] != ZERO]
        else:
            prepare = [f'CX q{g[k]} q{f[k]}' for k in range(WORD)]
        return AndXor(prepare, e, f, g)

    def maj(self, a, b, c):
        """Maj(a, b, c) = c ^ ((a ^ c) & (b ^ c)). a is the newest."""
        if isinstance(a, C):
            assert isinstance(b, C) and isinstance(c, C)
            return self.cw_maj(a, b, c)
        if isinstance(b, C):
            assert isinstance(c, C)  # Maj = bc ^ a(b ^ c).
            return Lin([([(a[k], self.c_xor(b[k], c[k]))], self.c_and(b[k], c[k])) for k in range(WORD)])
        if isinstance(c, C):
            prepare = [f'X q{q[k]} if b{c[k]}' if c[k] >= 0 else f'X q{q[k]}'
                       for k in range(WORD) if c[k] != ZERO for q in (a, b)]
        else:
            prepare = [f'CX q{c[k]} q{q[k]}' for k in range(WORD) for q in (a, b)]
        return AndXor(prepare, a, b, c)

    def split(self, terms: list) -> tuple[list, C]:
        """Splits terms into addends on qubits and the classical sum of the rest."""
        quantum, lump = [], const(0)
        for term in terms:
            if isinstance(term, C):
                lump = self.cw_add(lump, term)
            elif isinstance(term, list):
                quantum.append(Reg(term))
            else:
                quantum.append(term)
        return quantum, lump

    def round(self, t: int, state: list, w, *, need_a: bool = True, a_if: int | None = None,
              into_a: C = const(0), into_e: C = const(0)) -> list:
        """One round. Returns the new a..h.

        T1 = h + Sigma1(e) + Ch(e,f,g) + K_t + W_t, the new e is d + T1 and the new a is
        T1 + Sigma0(a) + Maj(a,b,c). Words are classical or quantum; whatever is classical
        is summed on classical bits and enters as one addend. `into_a` and `into_e` are
        classical words added to the new a and the new e. With `a_if`, the new a is
        only finished when that classical bit is set.
        """
        a, b, c, d, e, f, g, h = state
        base = None if isinstance(h, C) else h
        first, lump1 = self.split([const(K[t]), w, self.ch(e, f, g),
                                   self.cw_sigma(e, BIG_SIGMA1) if isinstance(e, C) else self.sigma(e, BIG_SIGMA1)]
                                  + ([h] if base is None else []))
        if not need_a:  # Only the new e is wanted. T1 is left behind in h's register.
            assert base is not None and not isinstance(d, C)
            total = self.accumulate(base, first, lump1)
            self.add(d, total, self.take(TOP))
            self.add_classical(d, into_e)
            return [None, a, b, c, d, e, f, g]

        second, lump2 = self.split([self.maj(a, b, c),
                                    self.cw_sigma(a, BIG_SIGMA0) if isinstance(a, C) else self.sigma(a, BIG_SIGMA0)])
        if base is None and not first:  # T1 is classical, and then so is d.
            new_e = self.cw_add(self.cw_add(d, lump1), into_e)
            lump = self.cw_add(self.cw_add(lump1, lump2), into_a)
            new_a = self.accumulate(None, second, lump) if second else lump
        elif isinstance(d, C):
            # One register gets T1 plus what is classical in the new a. The new e starts as
            # a copy of it and gets the classical difference.
            extra = self.cw_add(lump2, into_a)
            total = self.accumulate(base, first, self.cw_add(lump1, extra))
            new_e = self.materialize(Reg(total))
            self.add_classical(new_e, self.cw_add(self.cw_sub(d, extra), into_e))
            new_a = self.accumulate(total, second, const(0))
        else:
            total = self.accumulate(base, first, self.cw_add(lump1, into_a))
            self.add(d, total, self.take(TOP))
            self.add_classical(d, self.cw_sub(into_e, into_a))
            new_e = d
            self.begin(a_if)
            new_a = self.accumulate(total, second, lump2)
            self.end(a_if)
        return [new_a, a, b, c, new_e, e, f, g]

    def schedule(self, w: list, t: int):
        """W_t = W_(t-16) + sigma0(W_(t-15)) + W_(t-7) + sigma1(W_(t-2)), over W_(t-16) when that is quantum."""
        x16, x15, x7, x2 = w[t - 16], w[t - 15], w[t - 7], w[t - 2]
        base = None if isinstance(x16, C) else x16
        terms = [self.cw_sigma(x15, SMALL_SIGMA0) if isinstance(x15, C) else self.sigma(x15, SMALL_SIGMA0),
                 x7,
                 self.cw_sigma(x2, SMALL_SIGMA1) if isinstance(x2, C) else self.sigma(x2, SMALL_SIGMA1)]
        quantum, lump = self.split(terms + ([x16] if base is None else []))
        if base is None and not quantum:
            return lump
        return self.accumulate(base, quantum, lump)

    def compress(self, name: str, state: list, block: list, feed_forward: list, *, last: bool = False) -> list:
        """`compress(state, block)`; returns the eight words of the result.

        `state` words that are quantum are overwritten. `feed_forward` is the starting state
        again, as classical words or as registers that are left alone. With `last`, only
        H_5, H_6 and H_7 are computed and the other five entries are None.
        """
        start = self.ands, self.erased
        w = list(block)
        classical_ff = isinstance(feed_forward[0], C)
        rounds = 63 if last else 64
        for t in range(rounds):
            options, only_if = {}, None
            if last:
                # H_5 = IV_5 + e after 63 rounds, and H_6, H_7 come from the two e before it.
                # None of them needs a after round 58. Round 62 and the a of round 58 serve
                # H_5 alone; round 61 and the a of round 57 serve H_5 and H_6 alone.
                options['need_a'] = t < 59
                only_if = {61: self.need_h6, 62: self.need_h5}.get(t)
                options['a_if'] = {57: self.need_h6, 58: self.need_h5}.get(t)
                if t == 62:
                    options['into_e'] = feed_forward[5]
            elif t == 63 and classical_ff:
                options['into_a'], options['into_e'] = feed_forward[0], feed_forward[4]
            self.begin(only_if)
            if t >= 16:
                w.append(self.schedule(w, t))
            state = self.round(t, state, w[t], **options)
            self.end(only_if)
        if last:
            out = [None] * 5 + state[4:7]
            self.begin(self.need_h6)
            self.add_classical(out[6], feed_forward[6])
            self.end(self.need_h6)
            self.add_classical(out[7], feed_forward[7])
        else:
            out = state
            for j in range(8):
                if classical_ff:
                    if j not in (0, 4):
                        self.add_classical(out[j], feed_forward[j])
                else:
                    self.add(out[j], feed_forward[j], self.take(TOP))
        self.parts.append((name, self.ands - start[0], self.erased - start[1]))
        return out

    # ---- the oracle --------------------------------------------------------------------------

    def target(self) -> list[int]:
        """96 classical bits holding the target from bit 160 up: `M * 256^(e - 0x17)`."""
        base = self.bit_base['bits']
        exponent = [base + j for j in range(8)]
        mantissa = [base + 24 - 8 * (m // 8) + m % 8 for m in range(24)]
        not_exponent = [self.c_not(x) for x in exponent]
        target = [self.new_bit() for _ in range(96)]
        # H_5 holds bits 160 to 191 of the hash and H_6 bits 192 to 223. With the mantissa at
        # byte s, the bits below 160 + 8 s do not matter.
        self.need_h5, self.need_h6 = self.new_bit(), self.new_bit()
        for s in range(MAX_EXPONENT - MIN_EXPONENT + 1):  # Exponent 0x17 + s: the mantissa starts at byte s.
            selected = self.new_bit()
            lines = [f'BIT_INVERT b{selected}']
            for j in range(8):
                wrong = not_exponent[j] if ((MIN_EXPONENT + s) >> j) & 1 else exponent[j]
                lines.append(f'BIT_STORE0 b{selected} if b{wrong}')
            lines.append(f'PUSH_CONDITION if b{selected}')
            lines += [f'BIT_INVERT b{target[8 * s + m]} if b{mantissa[m]}' for m in range(24)]
            lines.append('POP_CONDITION')
            if s < 4:
                lines.append(f'BIT_INVERT b{self.need_h5} if b{selected}')
            if s < 8:
                lines.append(f'BIT_INVERT b{self.need_h6} if b{selected}')
            self.classical('\n'.join(lines))
        return target

    def less_than(self, value: list[int], target: list[int]) -> list[str]:
        """Prepares the phase flip for `value < target` and returns the gates that apply it.

        The flip is wanted when `value - target` borrows out of the top. borrow' =
        Maj(not value_i, target_i, borrow), one AND per bit, and the borrows stay in qubits
        until the backward half measures them away. The last AND is not computed: its
        phase is a CZ on its two inputs.

        The first 32 bits are H_5 and the next 32 are H_6. When the target is zero there,
        nothing borrows, so those bits are skipped under the same classical bits that skip
        the rounds computing them.
        """
        skip = {0: self.need_h5, 32: self.need_h6}
        region = None
        borrow = self.alloc()
        for i, (v, bit) in enumerate(zip(value, target)):
            if i in (0, 32, 64):
                self.end(region)
                region = skip.get(i)
                self.begin(region)
            if i == 0:
                self.x(v), self.cxc(v, borrow, bit), self.x(v)
                continue
            self.x(v), self.cx(borrow, v), self.xc(borrow, bit)
            if i == len(value) - 1:  # Maj = (borrow ^ bit)(not v ^ borrow) ^ borrow.
                unflip = [f'X q{borrow} if b{bit}']
                return [f'CZ q{borrow} q{v}'] + unflip + [f'Z q{borrow}'] + unflip
            t = self.and_(borrow, v)
            self.xc(borrow, bit), self.cx(borrow, t), self.cx(borrow, v), self.x(v)
            borrow = t

    def build(self) -> str:
        iv = [const(x) for x in IV]
        extranonce, nonce = list(range(48)), list(range(48, 80))

        # The coinbase's last block: extranonce ‖ tail, from the classical midstate.
        midstate = [self.input_word('midstate', WORD * j) for j in range(8)]
        low = self.alloc_word(16)
        for k in range(16):
            self.xc(low[k], self.bit_base['tail'] + k)
        block = [extranonce[:32], low + extranonce[32:]]
        block += [self.input_word('tail', 16 + WORD * (j - 2)) for j in range(2, 16)]
        inner1 = self.compress('coinbase, last block', midstate, block, midstate)

        # Its second hash: the merkle root.
        pad256 = [const(x) for x in PAD256]
        root = self.compress('merkle root', iv, inner1 + pad256, iv)

        # The header's first block: version ‖ prev_hash ‖ root[0:28]. Nine classical words.
        block = [self.input_word('version', 0)]
        block += [self.input_word('prev_hash', WORD * j) for j in range(8)]
        mid = self.compress('header, first block', iv, block + root[:7], iv)

        # The header's second block: root[28:32] ‖ time ‖ bits ‖ nonce ‖ padding. The rounds
        # work on a copy of the midstate, which is added back at the end.
        block = [root[7], self.input_word('time', 0), self.input_word('bits', 0), nonce]
        block += [const(x) for x in PAD640]
        working = [self.materialize(Reg(word)) for word in mid]
        inner2 = self.compress('header, second block', working, block, mid)

        # The block hash, H_5 to H_7 only.
        target = self.target()
        digest = self.compress('block hash', iv, inner2 + pad256, iv, last=True)

        for j in range(3):
            for k in range(WORD):
                self.xc(digest[5 + j][k], self.bit_base['mask'] + WORD * j + k)
        # Bit p of the hash as an integer is in byte p // 8, which is bit 8 (3 - i % 4) + p % 8 of word i // 4.
        value = [digest[(p // 8) // 4][8 * (3 - (p // 8) % 4) + p % 8] for p in range(160, 256)]
        kernel = self.less_than(value, target)

        measured = self.measured
        lines = []
        index = 0
        qubit = bit = 0
        for name, size, quantum in REGISTERS:
            kind, start = ('q', qubit) if quantum else ('b', bit)
            lines += [f'APPEND_TO_REGISTER {kind}{i} r{index}' for i in range(start, start + size)]
            lines.append(f'REGISTER r{index} "{name}"')
            if quantum:
                qubit += size
            else:
                bit += size
            index += 1
        for op in self.ops:
            if isinstance(op, str):
                lines.append(op)
            elif op[0] == 'A':
                lines.append(f'CCX q{op[1]} q{op[2]} q{op[3]}')
            elif op[0] == 'D':
                lines.append(f'HMR q{op[3]} b{measured}\nCZ q{op[1]} q{op[2]} if b{measured}')
            elif op[0] == 'P':
                lines.append(f'PUSH_CONDITION if b{op[1]}')
            elif op[0] == 'Q':
                lines.append('POP_CONDITION')
            else:
                lines.append(op[1])
        lines += kernel
        for op in reversed(self.ops):
            if isinstance(op, str):
                lines.append(op)
            elif op[0] == 'A':
                lines.append(f'HMR q{op[3]} b{measured}\nCZ q{op[1]} q{op[2]} if b{measured}')
            elif op[0] == 'D':
                lines.append(f'CCX q{op[1]} q{op[2]} q{op[3]}')
            elif op[0] == 'Q':
                lines.append(f'PUSH_CONDITION if b{op[1]}')
            elif op[0] == 'P':
                lines.append('POP_CONDITION')
        return '\n'.join(lines)


def build(max_qubits: int = MAX_QUBITS) -> tuple[Builder, km.Circuit]:
    """Builds with as many kept ANDs as fit in `max_qubits`."""
    bare = Builder(0)
    bare.build()
    keep = max_qubits - bare.next_qubit
    while True:
        builder = Builder(keep)
        text = builder.build()
        if builder.next_qubit <= max_qubits:
            return builder, km.Circuit(text)
        keep -= builder.next_qubit - max_qubits


def main(qubits: int | None = None, directory: pathlib.Path = _HERE) -> None:
    """Builds, checks and writes `circuit.kmb.zst` into `directory`.

    Args:
        qubits: The most the circuit may use. Left out, it is the command line's first
            argument, or 65,536.
        directory: Where the file goes. The entries that build this circuit on fewer qubits
            pass their own.
    """
    if qubits is None:
        qubits = int(sys.argv[1]) if len(sys.argv) > 1 else MAX_QUBITS
    builder, circuit = build(qubits)
    stats = circuit.operation_statistics()
    print(f'{circuit.num_qubits} qubits, {stats.num_toffoli_like} Toffolis, {len(circuit)} operations; '
          f'{builder.ands} ANDs forward, {builder.kept} of them kept, {builder.erased} computed again.')
    for name, ands, erased in builder.parts:
        print(f'  {name}: {ands} ANDs forward, {erased} again backward')
    reference.check(circuit)
    buffer = io.BytesIO()
    circuit.to_file(buffer, format='kmb')
    path = directory / 'circuit.kmb.zst'
    path.write_bytes(zstd.compress(buffer.getvalue(), level=19))
    print(f'Wrote {path.name}: {len(buffer.getvalue())} bytes ({path.stat().st_size} compressed). '
          'Matches hashlib on 1024 made-up blocks.')


if __name__ == '__main__':
    main()
