"""Builds a low-reaction-depth phase oracle for the problem `bitcoin-mining-v1`.

    |extranonce, nonce>  ->  (-1)^f |extranonce, nonce>

Written for the reaction-depth track (qubits x reaction depth). The contract is
sha256_verifier/docs/bitcoin-mining-v1.md. It starts from `../bitcoin-mining-low-depth`
(1,249 qubits at depth 4,435) and holds 119 qubits fewer at a depth 104 lower.

The five compressions are built with the sums of `../lean-lookahead-rounds`: carry-save
rows and a log-depth adder, 7 reactions per round on the way forward and 7 per round on the
way back. As in the circuit this starts from, a value that is no longer needed is measured
away in the X basis, and the phase this leaves is cancelled with Z gates when the same
value is computed again. A value computed again starts from the search register, so it is
no deeper than the first time: computing again costs operations and no depth. What is new:

- Forward rounds clear nothing. The registers a round is done with (the helper, h and d)
  are measured away, and the round that undoes it, which forms those values anyway,
  corrects their phase. A forward round is then well under half the operations of one
  that clears them.
- With the operations this frees, the circuit computes more often and holds less. Undoing a
  compression needs the output of the one before, and that is now computed again from the
  search register each time, with nothing else held: 18 passes of 64 rounds, of which 13
  are forward passes. The most the circuit ever holds is what the header's second block
  needs by itself: its schedule window, the midstate and its own state.
- That window is the schedule in place over the nonce and over the last word of the merkle
  root, with no copies.
- A round keeps one register beyond the eight of the state, not two: h is measured away
  before e' is formed, and a' is formed with e' - d, written into the register of d, as the
  adder's operand.
- In the three passes over the header's second block, and one more that runs next to a held
  value, additions use the adder of the lean rounds itself: 26 scratch qubits.

Usage, from this directory:

    uv run --project ../../sha256_verifier python build.py
"""

from __future__ import annotations

import heapq
import importlib.util
import pathlib
import sys

import kickmix as km

_HERE = pathlib.Path(__file__).parent


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lean = _load('lean_build', _HERE.parent / 'lean-lookahead-rounds' / 'build.py')
reference = _load('bitcoin_baseline_build', _HERE.parent / 'bitcoin-mining-baseline' / 'build.py')

WORD, K, IV, MASK = lean.WORD, lean.K, lean.IV, lean.MASK
Poly, sigma, ch, maj, inv = lean.Poly, lean.sigma, lean.ch, lean.maj, lean.inv
PAD256, PAD640 = reference.PAD256, reference.PAD640
MIN_EXPONENT, MAX_EXPONENT = reference.MIN_EXPONENT, reference.MAX_EXPONENT

AHEAD = 2          # The schedule runs this many words ahead of the rounds.
LAST_ROUNDS = 63   # The last compression runs rounds 0 .. 62,
LAST_FULL = 59     # and from this round on it forms no new a.
ROOMY = ('hash',)  # Compressions whose rounds use a register more; see `roomy_round`.

# Classical input registers, in the order the contract gives them: (name, bits).
CLASSICAL = (('midstate', 256), ('tail', 464), ('version', 32), ('prev_hash', 256), ('time', 32),
             ('bits', 32), ('mask', 96))
SEARCH_QUBITS = 80


# ---- gate emitter ------------------------------------------------------------------------

class Emitter(lean.Emitter):
    """The emitter of the lean rounds, with classical bits by number, operations under a
    classical condition, a heap for the free qubits and output in chunks."""

    def __init__(self, first_free: int, first_bit: int, resets: bool = True) -> None:
        super().__init__(first_free, [], resets)
        self.cd: dict[int, int] = {}
        self.next_bit = first_bit
        self.scratch_bit = self.new_bit()
        self.chunks: list[str] = []
        self.count = 0
        self.marks: list[tuple[str, int, int, int]] = []
        self.adder = 'wide'  # Which adder additions use: 'wide', 'narrow' or 'lean'.

    # Qubits and bits.

    def alloc(self, n: int) -> list[int]:
        out = []
        for _ in range(n):
            if self.free:
                out.append(heapq.heappop(self.free))
            else:
                out.append(self.next)
                self.next += 1
        return out

    def release(self, qubits: list[int], *, reset: bool = True) -> None:
        for q in qubits:
            if reset:
                self.r(q)
            heapq.heappush(self.free, q)

    def new_bit(self) -> int:
        self.next_bit += 1
        return self.next_bit - 1

    # Output.

    def flush(self) -> None:
        if self.ops:
            self.count += len(self.ops)
            self.chunks.append('\n'.join(self.ops))
            self.ops.clear()

    def emit(self, op: str) -> None:
        self.ops.append(op)
        if len(self.ops) >= 1 << 20:
            self.flush()

    def depth(self) -> int:
        return max(max(self.xd.values(), default=0), max(self.zd.values(), default=0),
                   max(self.cd.values(), default=0))

    def mark(self, label: str) -> None:
        self.marks.append((label, self.count + len(self.ops), self.depth(), self.next))

    # Operations. The ones inherited from the lean emitter append to `self.ops` directly.

    def x_if(self, q: int, bit: int) -> None:
        self.emit(f'X q{q} if b{bit}')
        self._bump(self.xd, q, self.cd.get(bit, 0))

    def cx_if(self, c: int, t: int, bit: int) -> None:
        self.emit(f'CX q{c} q{t} if b{bit}')
        d = self.cd.get(bit, 0)
        self._bump(self.xd, t, max(d, self.xd.get(c, 0)))
        self._bump(self.zd, c, max(d, self.zd.get(t, 0)))

    def z(self, q: int) -> None:
        self.emit(f'Z q{q}')

    def z_if(self, q: int, bit: int) -> None:
        self.emit(f'Z q{q} if b{bit}')
        self._bump(self.zd, q, self.cd.get(bit, 0))

    def measure(self, q: int, bit: int) -> None:
        """Measures q in the X basis into `bit` and resets it. A phase correction must follow."""
        self.emit(f'HMR q{q} b{bit}')
        self.cd[bit] = self.zd.get(q, 0) + 1
        self.xd[q] = self.zd[q] = 0

    def cz_on(self, a: int, b: int, bit: int) -> None:
        self.emit(f'CZ q{a} q{b} if b{bit}')
        d = self.cd.get(bit, 0)
        self._bump(self.zd, a, max(d, self.xd.get(b, 0)))
        self._bump(self.zd, b, max(d, self.xd.get(a, 0)))

    def hmr(self, q: int, bit: str = '') -> None:  # For the lean adder, which names one bit.
        self.measure(q, self.scratch_bit)

    def cz_if(self, a: int, b: int, bit: str) -> None:
        self.cz_on(a, b, self.scratch_bit)

    def classical(self, op: str) -> None:
        """An operation on classical bits that depend only on the inputs: depth zero."""
        self.emit(op)


# ---- carry-lookahead adder ---------------------------------------------------------------

SPLIT = 15  # The narrow adder handles the bits below and from this position separately.

_PLANS: dict[tuple[int, int, bool], tuple[list, list, list]] = {}


def prefix_plan(n: int, offset: int = 1, full: bool = False):
    """The Sklansky network for the carries out of positions 0 .. n - 1.

    Position i sits at index i + offset of a grid. With offset 1 the first index is empty,
    as in the lean adder, so the carries of a 32-bit addition have AND-depth 5. A merge is
    G[I] ^= R(l, I) & G[J], where R(l, I) is the product of the propagate bits from the
    start of I's block of 2^l to I. Those products are the `nodes`: each is the AND of two
    products one level down, or of propagate bits. With `full`, the third list gives for
    every position the product of all propagate bits up to it, which is what a carry into
    position 0 is multiplied by.
    """
    if (n, offset, full) in _PLANS:
        return _PLANS[n, offset, full]
    nodes, made = [], set()
    top = (n + offset - 1).bit_length()

    def product(level: int, index: int):
        if level == 0:
            return (0, index)
        if not (index >> (level - 1)) & 1:
            return product(level - 1, index)
        key = (level, index)
        if key not in made:
            below = ((index >> (level - 1)) << (level - 1)) - 1
            factors = product(level - 1, index), product(level - 1, below)
            made.add(key)
            nodes.append((key, *factors))
        return key

    merges = []
    for level in range(top):
        steps = []
        for index in range(offset, n + offset):
            if (index >> level) & 1:
                source = ((index >> level) << level) - 1
                if source >= offset:
                    steps.append((index, product(level, index), source))
        merges.append(steps)
    prefixes = [product(top, index) for index in range(offset, n + offset)] if full else []
    _PLANS[n, offset, full] = nodes, merges, prefixes
    return _PLANS[n, offset, full]


def prefix(em: Emitter, p: list[int], g: list[int], inverse: bool = False, offset: int = 1,
           carry_in: int | None = None) -> None:
    """Turns g[i] = generate of position i into the carry out of position i, or back.

    The products of propagate bits are built in scratch qubits, used by every merge that
    needs them, and measured away. With `carry_in`, a qubit holding the carry into
    position 0, the carries include it.
    """
    nodes, merges, prefixes = prefix_plan(len(g), offset, carry_in is not None)
    held: dict[tuple[int, int], int] = {}

    def qubit(key) -> int:
        return p[key[1] - offset] if key[0] == 0 else held[key]

    def block() -> None:
        for steps in (reversed(merges) if inverse else merges):
            for index, key, source in steps:
                em.ccx(qubit(key), g[source - offset], g[index - offset])

    def carry() -> None:
        if carry_in is not None:
            for i, key in enumerate(prefixes):
                em.ccx(qubit(key), carry_in, g[i])

    for key, f1, f2 in nodes:
        t = em.alloc(1)[0]
        em.ccx(qubit(f1), qubit(f2), t)
        held[key] = t
    for step in ((carry, block) if inverse else (block, carry)):
        step()
    for key, f1, f2 in reversed(nodes):
        em.measure(held[key], em.scratch_bit)
        em.cz_on(qubit(f1), qubit(f2), em.scratch_bit)
        em.release([held.pop(key)], reset=False)


def add_register(em: Emitter, a: list[int], b: list[int]) -> None:
    """`b += a` modulo 2^32 in place, for two registers. AND-depth 5.

    The carries are XORed into b and then erased: carries(a, b) == carries(a, ~s) for
    s = a + b (Draper), so the network run backwards on (a, ~s) turns them into a & ~s.

    This is the wide adder: 80 scratch qubits and about 730 operations. `em.adder` selects
    two others. The narrow one does the word in two parts, as the lean adder does: bits
    below SPLIT first, then the rest, with only the carry into bit SPLIT kept in between,
    erased at the end by computing the lower carries once more from (a, ~s). It needs 49
    scratch qubits and about 1,000 operations. The lean one is the adder of the lean rounds
    itself, which builds every product of propagate bits anew for the gate that needs it:
    26 scratch qubits and about 1,860 operations.
    """
    if em.adder == 'lean':
        lean.add(em, Poly.reg(a), b)
        return
    narrow = em.adder == 'narrow'
    n = len(b)
    parts = ((0, SPLIT), (SPLIT, n - 1)) if narrow else ((0, n - 1),)  # The top bit gives no carry.
    kept = em.alloc(1)[0] if narrow else None

    def generates(lo: int, hi: int, g: list[int]) -> None:
        """g[i] ^= a_i & b_i and b_i ^= a_i, which turns b into the propagates."""
        for i in range(lo, hi):
            em.ccx(a[i], b[i], g[i - lo])
            em.cx(a[i], b[i])

    def ungenerates(lo: int, hi: int, g: list[int]) -> None:
        for i in range(lo, hi):
            em.cx(a[i], b[i])
            em.ccx(a[i], b[i], g[i - lo])

    for lo, hi in parts:
        g = em.alloc(hi - lo)
        offset = 0 if lo else 1
        carry_in = kept if lo else None
        generates(lo, hi, g)
        if hi == n - 1:
            em.cx(a[n - 1], b[n - 1])
        prefix(em, b[lo:hi], g, offset=offset, carry_in=carry_in)
        if lo:
            em.cx(kept, b[lo])
        elif kept is not None:
            em.cx(g[hi - 1 - lo], kept)  # The carry into bit SPLIT; it goes into b later.
        for i in range(lo, hi):
            if i + 1 < (n if hi == n - 1 else hi):
                em.cx(g[i - lo], b[i + 1])  # b = s.
        for i in range(lo, hi):
            em.x(b[i])
            em.cx(a[i], b[i])  # b = a ^ ~s.
        prefix(em, b[lo:hi], g, inverse=True, offset=offset, carry_in=carry_in)  # g[i] = a_i & ~s_i.
        ungenerates(lo, hi, g)
        for i in range(lo, hi):
            em.x(b[i])
        em.release(g)
    if kept is not None:
        g = em.alloc(SPLIT)
        for i in range(SPLIT):
            em.x(b[i])
        generates(0, SPLIT, g)
        prefix(em, b[:SPLIT], g)
        em.cx(g[SPLIT - 1], kept)
        prefix(em, b[:SPLIT], g, inverse=True)
        ungenerates(0, SPLIT, g)
        for i in range(SPLIT):
            em.x(b[i])
        em.release(g + [kept])


def _as_register(row):
    """The qubits of a row that is exactly one register, or None."""
    if not isinstance(row, Poly) or row.const:
        return None
    out = []
    for bit in row.bits:
        if len(bit) != 1:
            return None
        (m,) = bit
        if len(m) != 1:
            return None
        out.append(next(iter(m)))
    return out


def add_row(em: Emitter, row, b: list[int], subtract: bool = False) -> None:
    """`b += row`, or `b -= row`. A row that is not a register is written into scratch
    qubits for the addition and taken out again after it."""
    if subtract:  # b - a = ~(~b + a)
        for q in b:
            em.x(q)
    operand = _as_register(row)
    if operand is not None:
        add_register(em, operand, b)
    else:
        operand = em.alloc(WORD)
        for k in range(WORD):
            lean.row_xor_into(em, row, k, operand[k])
        add_register(em, operand, b)
        for k in range(WORD):
            lean.row_xor_into(em, row, k, operand[k])
        em.release(operand)
    if subtract:
        for q in b:
            em.x(q)


def sum_into(em: Emitter, target: list[int], holder: list[int], linear, quad, subtract: bool = False) -> None:
    """`target += V`, or `target -= V`, for V = holder + linear + quad: a register, an
    XOR-linear row and a quadratic row. With `subtract`, target holds V and ends at zero;
    without, it starts at zero.

    One carry-save step leaves two rows. Its carry row is XORed into the target bit by bit
    and never stored. The other row is holder ^ linear ^ quad, so those two are XORed into
    `holder` for the addition and out again after it: the register that is the adder's
    operand is one the round has anyway.
    """
    first = lean.MajRow(Poly.reg(holder), linear, quad)
    correction = linear ^ quad
    if not subtract:
        for k in range(WORD):
            lean.row_xor_into(em, first, k, target[k])
    for k in range(WORD):
        lean.xor_bit(em, correction.bit(k), holder[k])
    add_row(em, Poly.reg(holder), target, subtract)
    for k in range(WORD):
        lean.xor_bit(em, correction.bit(k), holder[k])
    if subtract:
        for k in range(WORD):
            lean.row_xor_into(em, first, k, target[k])


def create(em: Emitter, terms, const: int = 0, cin: int = 0, tail: int = 0) -> list[int]:
    """A fresh register holding (sum(terms) + const + cin) mod 2^32. The last `tail` terms
    are the ones that are ready last; they go into the carry-save steps last."""
    first, operand = lean.two_rows(em, terms, const, cin, tail)
    out = em.alloc(WORD)
    for k in range(WORD):
        lean.row_xor_into(em, first, k, out[k])
    if not lean._is_zero(operand):
        add_row(em, operand, out)
    return out


def clear(em: Emitter, reg: list[int], terms, const: int = 0, cin: int = 0, tail: int = 0) -> None:
    """Clears and frees `reg`, which holds sum(terms) + const + cin: subtracts one row in
    place and XORs the other away."""
    first, operand = lean.two_rows(em, terms, const, cin, tail)
    if not lean._is_zero(operand):
        add_row(em, operand, reg, subtract=True)
    for k in range(WORD):
        lean.row_xor_into(em, first, k, reg[k])
    em.release(reg)


# ---- the oracle --------------------------------------------------------------------------

class Builder:
    def __init__(self, resets: bool = True) -> None:
        self.bit = {}
        start = 0
        for name, size in CLASSICAL:
            self.bit[name] = list(range(start, start + size))
            start += size
        self.em = Emitter(SEARCH_QUBITS, start, resets)
        self.extranonce = list(range(48))
        self.nonce = list(range(48, 80))
        # The bits of every register a forward round measured away, by (compression, round, name).
        self.measured: dict[tuple, list[list[int]]] = {}

    # Loading and unloading. Each of these is its own inverse.

    def words(self, name: str) -> list[list[int]]:
        bits = self.bit[name]
        return [bits[WORD * j:WORD * (j + 1)] for j in range(len(bits) // WORD)]

    def load_bits(self, reg: list[int], bits: list[int]) -> None:
        for q, b in zip(reg, bits):
            self.em.x_if(q, b)

    def load_constant(self, reg: list[int], value: int) -> None:
        for k, q in enumerate(reg):
            if (value >> k) & 1:
                self.em.x(q)

    def copy(self, source: list[int], target: list[int]) -> None:
        for s, t in zip(source, target):
            self.em.cx(s, t)

    def fresh(self, count: int = 1) -> list[list[int]]:
        return [self.em.alloc(WORD) for _ in range(count)]

    def add_classical(self, bits: list[int], target: list[int], subtract: bool = False) -> None:
        operand = self.em.alloc(WORD)
        self.load_bits(operand, bits)
        add_row(self.em, Poly.reg(operand), target, subtract)
        self.load_bits(operand, bits)
        self.em.release(operand)

    def add_constant(self, value: int, target: list[int], subtract: bool = False) -> None:
        operand = self.em.alloc(WORD)
        self.load_constant(operand, value)
        add_row(self.em, Poly.reg(operand), target, subtract)
        self.load_constant(operand, value)
        self.em.release(operand)

    # The message schedule, in place over a window of 16 registers.

    @staticmethod
    def schedule_terms(win, t: int):
        """W_t - W_(t-16) as rows: sigma0(W_(t-15)), W_(t-7), sigma1(W_(t-2))."""
        return (sigma(win[(t - 15) % 16], lean.SMALL_SIGMA0), Poly.reg(win[(t - 7) % 16]),
                sigma(win[(t - 2) % 16], lean.SMALL_SIGMA1))

    def schedule(self, win, t: int) -> None:
        """Turns W_(t-16) into W_t, the term that is ready last going last."""
        for term in self.schedule_terms(win, t):
            add_row(self.em, term, win[t % 16])

    def unschedule(self, win, t: int) -> None:
        """Turns W_t back into W_(t-16). Phase corrections flow from the register to the
        operands, and the next step has W_(t-2) as its register, so that term goes first."""
        for term in reversed(self.schedule_terms(win, t)):
            add_row(self.em, term, win[t % 16], subtract=True)

    def expand(self, win, last: int) -> None:
        for t in range(16, last + 1):
            self.schedule(win, t)

    def rewind(self, win, last: int) -> None:
        for t in reversed(range(16, last + 1)):
            self.unschedule(win, t)

    # Rounds. A holds the registers of a, b, c, d and E those of e, f, g, h.

    def add_complement(self, reg: list[int], target: list[int], subtract: bool = False) -> None:
        """`target += ~reg`, or `-=`."""
        for q in reg:
            self.em.x(q)
        add_row(self.em, Poly.reg(reg), target, subtract)
        for q in reg:
            self.em.x(q)

    def drop(self, reg: list[int], key: tuple) -> None:
        """Measures away a register that a forward round is done with."""
        self.measured.setdefault(key, []).append(self.measure_away([reg]))

    def fix(self, reg: list[int], key: tuple) -> None:
        """The phase corrections for every time `drop` measured this value."""
        for bits in self.measured.get(key, ()):
            self.correct([reg], bits)

    def roomy_round(self, win, A: list, E: list, t: int, tag: str, d=None, fold: int | None = None) -> None:
        """`round` with a register more: h, d and the helper stay until the round is done
        with them, and the sum for a' has a scratch register for its row. Its AND-depth
        does not chain from one `roomy_unround` to the next by more than 7."""
        em = self.em
        a, b, c, d_full = A
        e, f, g, h = E
        full = d is None
        d = d_full if full else d
        slot = win[t % 16]
        s1, chv = sigma(e, lean.BIG_SIGMA1), ch(e, f, g)
        u = em.alloc(WORD)
        e_new = em.alloc(WORD)
        if fold is None:
            self.load_constant(u, K[t])
            for reg in sorted((slot, d, h), key=lambda r: max(em.x_depth(x) for x in r)):
                add_register(em, reg, u)  # The term that is ready last goes last.
            sum_into(em, e_new, u, s1, chv)
        else:
            self.load_constant(u, (K[t] + fold) & MASK)
            for reg in (d, h):
                add_register(em, reg, u)
            sum_into(em, e_new, u, s1, chv)
            add_register(em, slot, e_new)
        self.drop(u, (tag, t, 'u'))
        self.drop(h, (tag, t, 'h'))
        if fold is not None:
            self.add_constant(fold, slot)  # Only now does the register hold the schedule word.
        E[:] = [e_new, e, f, g]
        if full:
            s0, mj = sigma(a, lean.BIG_SIGMA0), maj(a, b, c)
            a_new = create(em, [inv(d), e_new, s0, mj], cin=1, tail=2)
            self.drop(d, (tag, t, 'd'))
            A[:] = [a_new, a, b, c]

    def roomy_unround(self, win, A: list, E: list, t: int, tag: str, d=None, fold: int | None = None) -> None:
        """Undoes `roomy_round`."""
        em = self.em
        full = d is None
        slot = win[t % 16]
        if fold is not None:  # The word loses its constant first; see `round`.
            self.add_constant(fold, slot, subtract=True)
        if full:
            a_new, a, b, c = A
            s0, mj = sigma(a, lean.BIG_SIGMA0), maj(a, b, c)
            d = create(em, [E[0], inv(a_new), s0, mj], cin=1, tail=2)
            self.fix(d, (tag, t, 'd'))
            clear(em, a_new, [inv(d), E[0], s0, mj], cin=1, tail=2)
            A[:] = [a, b, c, d]
        e_new, e, f, g = E
        s1, chv = sigma(e, lean.BIG_SIGMA1), ch(e, f, g)
        constant = K[t] if fold is None else (K[t] + fold) & MASK
        u = em.alloc(WORD)
        self.load_constant(u, constant)
        for reg in (slot, d):
            add_register(em, reg, u)
        self.add_complement(e_new, u)
        h = em.alloc(WORD)
        sum_into(em, h, u, s1, chv)  # ~h = ~e' + W + K + d + Sigma1 + Ch
        for x in h:
            em.x(x)
        self.fix(h, (tag, t, 'h'))
        self.add_complement(e_new, u, subtract=True)
        if fold is None:
            add_register(em, h, u)
            self.fix(u, (tag, t, 'u'))
            sum_into(em, e_new, u, s1, chv, subtract=True)
            em.release(e_new)
            for reg in (h, d, slot):
                add_row(em, Poly.reg(reg), u, subtract=True)
        else:  # The word leaves e' first and directly.
            add_row(em, Poly.reg(slot), u, subtract=True)
            add_register(em, h, u)
            self.fix(u, (tag, t, 'u'))
            add_row(em, Poly.reg(slot), e_new, subtract=True)
            sum_into(em, e_new, u, s1, chv, subtract=True)
            em.release(e_new)
            for reg in (h, d):
                add_row(em, Poly.reg(reg), u, subtract=True)
        self.load_constant(u, constant)
        em.release(u)
        E[:] = [e, f, g, h]

    def reflect(self, reg: list[int], other: list[int]) -> None:
        """`reg = other - reg` in place: ~(reg + ~other). Its own inverse."""
        em = self.em
        for q in other:
            em.x(q)
        add_register(em, other, reg)
        for q in other:
            em.x(q)
        for q in reg:
            em.x(q)

    def round(self, win, A: list, E: list, t: int, tag: str, d=None, fold: int | None = None) -> None:
        """One round on the way forward:

            U  = W + K + d + h                             then h is measured away
            e' = U + Sigma1(e) + Ch(e, f, g)               then U is measured away
            D  = e' - d, in the register of d
            a' = D + Sigma0(a) + Maj(a, b, c)              then D is measured away

        The terms of e' that are ready early are added up in a helper register U, one
        in-place addition each, so that one carry-save step is left for the two late terms
        (see `sum_into`). Whatever the round is done with is measured away at once, so only
        one register beyond the eight of the state is ever alive. `unround` forms each
        measured value again and corrects the phase there.

        With `d` given, the round forms no a' and leaves d alone: for the last rounds of
        the last compression, whose a is never used.

        With `fold` given, the schedule word is the term that is ready last by far, and its
        register still lacks the constant `fold` (the feed-forward of the compression it
        comes from). Then everything else is summed first and the word is added last, in
        place, before its own constant is: 5 reactions after the word, not 17.
        """
        if tag in ROOMY:
            return self.roomy_round(win, A, E, t, tag, d, fold)
        em = self.em
        a, b, c, d_full = A
        e, f, g, h = E
        full = d is None
        d = d_full if full else d
        slot = win[t % 16]
        s1, chv = sigma(e, lean.BIG_SIGMA1), ch(e, f, g)
        u = em.alloc(WORD)
        if fold is None:
            self.load_constant(u, K[t])
            for reg in sorted((slot, d, h), key=lambda r: max(em.x_depth(x) for x in r)):
                add_register(em, reg, u)  # The term that is ready last goes last.
        else:
            self.load_constant(u, (K[t] + fold) & MASK)
            for reg in (d, h):
                add_register(em, reg, u)
        self.drop(h, (tag, t, 'h'))
        e_new = em.alloc(WORD)
        sum_into(em, e_new, u, s1, chv)
        if fold is not None:
            add_register(em, slot, e_new)
        self.drop(u, (tag, t, 'u'))
        if fold is not None:
            self.add_constant(fold, slot)  # Only now does the register hold the schedule word.
        E[:] = [e_new, e, f, g]
        if full:
            s0, mj = sigma(a, lean.BIG_SIGMA0), maj(a, b, c)
            self.reflect(d, e_new)
            a_new = em.alloc(WORD)
            sum_into(em, a_new, d, s0, mj)
            self.drop(d, (tag, t, 'd'))
            A[:] = [a_new, a, b, c]

    def unround(self, win, A: list, E: list, t: int, tag: str, d=None, fold: int | None = None) -> None:
        """Undoes a round, again with one register beyond the state:

            D = a' - Sigma0(a) - Maj(a, b, c)              then a' = D + (the rest) is cleared
            d = e' - D, in the register of D
            U = e' - Sigma1(e) - Ch(e, f, g)               then e' = U + (the rest) is cleared
            h = U - W - K - d, in the register of U

        a' and e' are cleared by subtracting a recomputation in place. D, U and h are the
        values the forward rounds measured away, and get their phase corrections here.
        """
        if tag in ROOMY:
            return self.roomy_unround(win, A, E, t, tag, d, fold)
        em = self.em
        full = d is None
        slot = win[t % 16]
        if fold is not None:  # The word loses its constant first; see `round`.
            self.add_constant(fold, slot, subtract=True)
        if full:
            a_new, a, b, c = A
            s0, mj = sigma(a, lean.BIG_SIGMA0), maj(a, b, c)
            d = em.alloc(WORD)
            self.complemented_sum(d, a_new, s0, mj)  # ~D = ~a' + Sigma0 + Maj
            self.fix(d, (tag, t, 'd'))
            sum_into(em, a_new, d, s0, mj, subtract=True)
            em.release(a_new)
            self.reflect(d, E[0])
            A[:] = [a, b, c, d]
        e_new, e, f, g = E
        s1, chv = sigma(e, lean.BIG_SIGMA1), ch(e, f, g)
        if fold is not None:  # The word leaves e' first and directly.
            add_row(em, Poly.reg(slot), e_new, subtract=True)
        u = em.alloc(WORD)
        self.complemented_sum(u, e_new, s1, chv)  # ~U = ~e' + Sigma1 + Ch
        self.fix(u, (tag, t, 'u'))
        sum_into(em, e_new, u, s1, chv, subtract=True)
        em.release(e_new)
        for reg in ((d,) if fold is not None else (slot, d)):
            add_row(em, Poly.reg(reg), u, subtract=True)
        self.add_constant(K[t] if fold is None else (K[t] + fold) & MASK, u, subtract=True)
        self.fix(u, (tag, t, 'h'))
        E[:] = [e, f, g, u]

    def complemented_sum(self, target: list[int], reg: list[int], linear, quad) -> None:
        """`target = reg - linear - quad` for a target at zero: ~target = ~reg + linear + quad."""
        em = self.em
        for q in reg:
            em.x(q)
        sum_into(em, target, reg, linear, quad)
        for q in reg:
            em.x(q)
        for q in target:
            em.x(q)

    @staticmethod
    def formed_before(rounds: int) -> list[list[int]]:
        """The schedule words formed just before each round."""
        plan, formed = [], 15
        for t in range(rounds):
            now = []
            while formed < min(t + AHEAD, rounds - 1):
                formed += 1
                now.append(formed)
            plan.append(now)
        return plan

    def rounds_forward(self, win, state: list, tag: str, rounds: int = 64, full: int = 64, start: int = 0,
                       late: tuple[int, int] | None = None) -> list:
        """Expands the schedule and runs the rounds from `start`. Returns the registers of
        the state. `late` is (round, constant) for the round that takes `fold`."""
        A, E = list(state[:4]), list(state[4:])
        for t, words in enumerate(self.formed_before(rounds)):
            for u in words:
                self.schedule(win, u)
            if t >= start:
                fold = late[1] if late and late[0] == t else None
                self.round(win, A, E, t, tag, None if t < full else A[3 - (t - full)], fold)
        return A + E

    def rounds_backward(self, win, state: list, tag: str, rounds: int = 64, full: int = 64, start: int = 0,
                        late: tuple[int, int] | None = None) -> list:
        """The inverse of `rounds_forward`. Leaves the block in the window."""
        A, E = list(state[:4]), list(state[4:])
        plan = self.formed_before(rounds)
        for t in reversed(range(rounds)):
            if t >= start:
                fold = late[1] if late and late[0] == t else None
                self.unround(win, A, E, t, tag, None if t < full else A[3 - (t - full)], fold)
            for u in reversed(plan[t]):
                self.unschedule(win, u)
        return A + E

    # Round 0 of a compression that starts from the initial value: e_1 and a_1 are the first
    # schedule word plus a constant each.

    @staticmethod
    def first_constants() -> tuple[int, int]:
        rotr = lambda x, n: ((x >> n) | (x << (WORD - n))) & MASK
        a, b, c, d, e, f, g, h = IV
        t1 = h + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + K[0]
        t2 = (rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))
        return (d + t1) & MASK, (t1 + t2) & MASK

    def first_round(self, word: list[int], pending) -> list:
        """The state after round 0. `pending` is what the word's register still lacks, the
        feed-forward of the compression it comes from, as classical bits; or None. It is
        added to the two sums as a third row, and to the register only afterwards."""
        em = self.em
        rows = [word]
        if pending is not None:
            rows.append(em.alloc(WORD))
            self.load_bits(rows[1], pending)
        e_new, a_new = (create(em, rows, const) for const in self.first_constants())
        if pending is not None:
            self.load_bits(rows[1], pending)
            em.release(rows[1])
            self.add_classical(pending, word)
        rest = self.padding([IV[0], IV[1], IV[2], IV[4], IV[5], IV[6]])
        return [a_new] + rest[:3] + [e_new] + rest[3:]

    def unfirst_round(self, word: list[int], state: list, pending) -> None:
        em = self.em
        a_new, e_new = state[0], state[4]
        rows = [word]
        if pending is not None:
            self.add_classical(pending, word, subtract=True)
            rows.append(em.alloc(WORD))
            self.load_bits(rows[1], pending)
        for reg, const in zip((e_new, a_new), self.first_constants()):
            clear(em, reg, rows, const)
        if pending is not None:
            self.load_bits(rows[1], pending)
            em.release(rows[1])
        self.drop_padding(state[1:4] + state[5:8], [IV[0], IV[1], IV[2], IV[4], IV[5], IV[6]])

    # States that are measured away.

    def measure_away(self, regs: list[list[int]]) -> list[int]:
        """Measures the registers in the X basis and frees them. Returns the bits."""
        bits = []
        for reg in regs:
            for q in reg:
                bit = self.em.new_bit()
                self.em.measure(q, bit)
                bits.append(bit)
            self.em.release(reg, reset=False)
        return bits

    def correct(self, regs: list[list[int]], bits: list[int]) -> None:
        """The phase correction for `measure_away`, on registers holding the same value."""
        qubits = [q for reg in regs for q in reg]
        for q, bit in zip(qubits, bits):
            self.em.z_if(q, bit)

    # The five compressions. Each `*_block` loads or unloads the classical part of a block.

    def coinbase_window(self) -> list[list[int]]:
        """extranonce ‖ tail. The schedule runs in place over the search register."""
        tail = self.bit['tail']
        low = self.em.alloc(16)
        self.load_bits(low, tail[0:16])
        win = [self.extranonce[0:32], low + self.extranonce[32:48]]
        for j in range(2, 16):
            reg = self.em.alloc(WORD)
            self.load_bits(reg, tail[16 + WORD * (j - 2):16 + WORD * (j - 1)])
            win.append(reg)
        return win

    def drop_coinbase_window(self, win) -> None:
        tail = self.bit['tail']
        self.load_bits(win[1][:16], tail[0:16])
        self.em.release(win[1][:16])
        for j in range(2, 16):
            self.load_bits(win[j], tail[16 + WORD * (j - 2):16 + WORD * (j - 1)])
            self.em.release(win[j])

    def coinbase(self) -> list:
        """inner1 from the search register. The window is rewound and dropped."""
        midstate = self.words('midstate')
        win = self.coinbase_window()
        state = self.fresh(8)
        for reg, bits in zip(state, midstate):
            self.load_bits(reg, bits)
        state = self.rounds_forward(win, state, 'coinbase')
        for reg, bits in zip(state[1:], midstate[1:]):  # The first word's goes in later.
            self.add_classical(bits, reg)
        self.rewind(win, 63)
        self.drop_coinbase_window(win)
        return state

    def uncoinbase(self, state: list) -> None:
        midstate = self.words('midstate')
        win = self.coinbase_window()
        self.expand(win, 63)
        for reg, bits in zip(state[1:], midstate[1:]):
            self.add_classical(bits, reg, subtract=True)
        state = self.rounds_backward(win, state, 'coinbase')
        for reg, bits in zip(state, midstate):
            self.load_bits(reg, bits)
            self.em.release(reg)
        self.drop_coinbase_window(win)

    def iv_state(self) -> list:
        state = self.fresh(8)
        for reg, value in zip(state, IV):
            self.load_constant(reg, value)
        return state

    def drop_iv_state(self, state: list) -> None:
        for reg, value in zip(state, IV):
            self.load_constant(reg, value)
            self.em.release(reg)

    def padding(self, values) -> list[list[int]]:
        regs = self.fresh(len(values))
        for reg, value in zip(regs, values):
            self.load_constant(reg, value)
        return regs

    def drop_padding(self, regs, values) -> None:
        for reg, value in zip(regs, values):
            self.load_constant(reg, value)
            self.em.release(reg)

    def digest_forward(self, digest: list, pending, tag: str, rounds: int = 64, full: int = 64):
        """compress(IV, digest ‖ pad256). The digest's registers become part of the window.
        `pending` is the feed-forward that the digest's first word still lacks, or None."""
        win = list(digest) + self.padding(PAD256)
        state = self.first_round(win[0], pending)
        state = self.rounds_forward(win, state, tag, rounds, full, start=1)
        return state, win

    def digest_backward(self, state: list, win, pending, tag: str, rounds: int = 64, full: int = 64) -> list:
        """Undoes `digest_forward` given the expanded window. Returns the digest, its first
        word without `pending`."""
        state = self.rounds_backward(win, state, tag, rounds, full, start=1)
        self.unfirst_round(win[0], state, pending)
        self.drop_padding(win[8:], PAD256)
        return win[:8]

    def header1_window(self, root7: list) -> list:
        """version ‖ prev_hash ‖ root[0:28]."""
        loaded = self.fresh(9)
        for reg, bits in zip(loaded, [self.bit['version']] + self.words('prev_hash')):
            self.load_bits(reg, bits)
        return loaded + list(root7)

    def drop_header1_window(self, win) -> list:
        for reg, bits in zip(win[:9], [self.bit['version']] + self.words('prev_hash')):
            self.load_bits(reg, bits)
            self.em.release(reg)
        return win[9:]

    def header2_window(self, root_last: list) -> list:
        """root[28:32] ‖ time ‖ bits ‖ nonce ‖ pad640. The two quantum words are the
        registers themselves, so the schedule runs in place over the nonce."""
        w1, w2 = self.fresh(2)
        self.load_bits(w1, self.bit['time'])
        self.load_bits(w2, self.bit['bits'])
        return [root_last, w1, w2, self.nonce] + self.padding(PAD640)

    def drop_header2_window(self, win) -> None:
        self.load_bits(win[1], self.bit['time'])
        self.load_bits(win[2], self.bit['bits'])
        self.em.release(win[1] + win[2])
        self.drop_padding(win[4:], PAD640)

    # The comparison.

    def target(self) -> list[int]:
        """96 classical bits holding the target from bit 160 up, `M · 256^(e − 0x17)`, as
        in the baseline: classical operations on the `bits` register."""
        em, bits = self.em, self.bit['bits']
        exponent = bits[0:8]
        mantissa = [bits[24 - 8 * (m // 8) + m % 8] for m in range(24)]
        not_exponent = [em.new_bit() for _ in range(8)]
        for nb, eb in zip(not_exponent, exponent):
            em.classical(f'BIT_STORE1 b{nb}')
            em.classical(f'BIT_INVERT b{nb} if b{eb}')
        target = [em.new_bit() for _ in range(96)]
        for tb in target:
            em.classical(f'BIT_STORE0 b{tb}')
        selected = em.new_bit()
        for s in range(MAX_EXPONENT - MIN_EXPONENT + 1):
            em.classical(f'BIT_STORE1 b{selected}')
            for j in range(8):
                wrong = not_exponent[j] if ((MIN_EXPONENT + s) >> j) & 1 else exponent[j]
                em.classical(f'BIT_STORE0 b{selected} if b{wrong}')
            em.classical(f'PUSH_CONDITION if b{selected}')
            for m in range(24):
                em.classical(f'BIT_INVERT b{target[8 * s + m]} if b{mantissa[m]}')
            em.classical('POP_CONDITION')
        return target

    def chunk_carry(self, value: list[int], target: list[int], generate: int, propagate: int) -> None:
        """generate ^= carry out of ~value + target, propagate ^= (every position
        propagates), for one 32-bit chunk. Its own inverse; restores `value`."""
        em = self.em
        n = len(value)
        g = em.alloc(n)
        for i in range(n):
            em.x(value[i])
            em.cx_if(value[i], g[i], target[i])
            em.x_if(value[i], target[i])  # value = the propagates.
        prefix(em, value, g)
        em.cx(g[n - 1], generate)
        top, levels = lean._and_tree(em, value)
        em.cx(top, propagate)
        for level in reversed(levels):
            for a, b, node in reversed(level):
                em.measure(node, em.scratch_bit)
                em.cz_on(a, b, em.scratch_bit)
                em.release([node], reset=False)
        prefix(em, value, g, inverse=True)
        for i in range(n):
            em.x_if(value[i], target[i])
            em.cx_if(value[i], g[i], target[i])
            em.x(value[i])
        em.release(g)

    def phase(self, h5: list[int], h6: list[int], h7: list[int]) -> None:
        """Flips the phase when the masked hash is below the target.

        v < T exactly when ~v + T carries out of the top bit. The 96 bits are done in
        three chunks, each giving its carry and whether it passes a carry on.
        """
        em = self.em
        digest = {5: h5, 6: h6, 7: h7}
        mask = self.bit['mask']
        for j in range(3):
            self.load_bits(digest[5 + j], mask[WORD * j:WORD * (j + 1)])
        # Bit p of the hash as an integer is bit 8 (3 - i % 4) + p % 8 of word i // 4, i = p // 8.
        value = [digest[(p // 8) // 4][8 * (3 - (p // 8) % 4) + p % 8] for p in range(160, 256)]
        target = self.target()
        gen, prop = em.alloc(3), em.alloc(3)

        def chunks() -> None:
            for c in range(3):
                self.chunk_carry(value[WORD * c:WORD * (c + 1)], target[WORD * c:WORD * (c + 1)], gen[c], prop[c])

        def combine() -> None:  # gen[2] ^= prop[2] & (gen[1] ^ prop[1] & gen[0])
            t = em.alloc(1)[0]
            em.ccx(prop[1], gen[0], t)
            em.cx(t, gen[1])
            em.ccx(prop[2], gen[1], gen[2])
            em.cx(t, gen[1])
            em.ccx(prop[1], gen[0], t)
            em.release([t])

        chunks()
        combine()
        em.z(gen[2])
        combine()
        chunks()
        em.release(gen + prop)
        for j in range(3):
            self.load_bits(digest[5 + j], mask[WORD * j:WORD * (j + 1)])

    # The whole circuit.

    def build(self) -> km.Circuit:
        em = self.em
        iv = list(IV)
        first_midstate = self.words('midstate')[0]
        windows: dict[str, list[int]] = {}  # The bits of the windows that were measured away.

        def to_root() -> list:
            """The merkle root from the search register. Its first word still lacks the
            feed-forward, which goes in at round 9 of the header's first block."""
            inner1 = self.coinbase()
            root, win = self.digest_forward(inner1, first_midstate, 'root')
            for reg, value in zip(root[1:], iv[1:]):
                self.add_constant(value, reg)
            if 'root' in windows:
                self.correct(win, windows['root'])
            windows['root'] = self.measure_away(win)
            return root

        def to_mid():
            """The header's midstate, the root's last word and the window of the header's
            first block, with the phase of its last measurement corrected."""
            root = to_root()
            win = self.header1_window(root[:7])
            mid = self.rounds_forward(win, self.iv_state(), 'header 1', late=(9, iv[0]))
            for reg, value in zip(mid, iv):
                self.add_constant(value, reg)
            if 'header 1' in windows:
                self.correct(win, windows['header 1'])
            return mid, root[7], win

        def to_inner2(mid: list, root_last: list):
            win = self.header2_window(root_last)
            inner2 = self.fresh(8)
            for source, reg in zip(mid, inner2):
                self.copy(source, reg)
            inner2 = self.rounds_forward(win, inner2, 'header 2')
            for source, reg in zip(mid, inner2):
                add_row(em, Poly.reg(source), reg)
            return inner2, win

        # Forward. Whatever the next compression does not need is measured away.
        mid, root_last, win = to_mid()
        windows['header 1'] = self.measure_away(win)
        em.mark('to the midstate')

        # The header's second block is where the circuit holds the most: its window, the
        # midstate and its own state. It uses the adder with the least scratch.
        em.adder = 'lean'
        inner2, win = to_inner2(mid, root_last)
        self.rewind(win, 63)  # The window holds the nonce, so it is rewound, not measured.
        self.drop_header2_window(win)
        em.adder = 'wide'
        held = self.measure_away(mid + [root_last])
        em.mark('header 2')

        state, win = self.digest_forward(inner2, None, 'hash', LAST_ROUNDS, LAST_FULL)
        compared = state[4:7]  # e_63, e_62, e_61: H_5, H_6, H_7 without the feed-forward.
        for reg, value in zip(compared, iv[5:8]):
            self.add_constant(value, reg)
        em.mark('hash')

        self.phase(*compared)
        em.mark('phase')

        # Backward. Undoing a compression needs the one before it, which is computed again
        # from the search register each time.
        for reg, value in zip(compared, iv[5:8]):
            self.add_constant(value, reg, subtract=True)
        inner2 = self.digest_backward(state, win, None, 'hash', LAST_ROUNDS, LAST_FULL)
        measured_inner2 = self.measure_away(inner2)
        em.mark('undo hash')

        mid, root_last, win = to_mid()
        windows['header 1'] = self.measure_away(win)
        self.correct(mid + [root_last], held)
        em.mark('to the midstate again')
        em.adder = 'lean'
        inner2, win = to_inner2(mid, root_last)
        self.correct(inner2, measured_inner2)
        for source, reg in zip(mid, inner2):
            add_row(em, Poly.reg(source), reg, subtract=True)
        inner2 = self.rounds_backward(win, inner2, 'header 2')
        for source, reg in zip(mid, inner2):
            self.copy(source, reg)
            em.release(reg)
        self.drop_header2_window(win)
        em.adder = 'wide'
        held = self.measure_away(mid + [root_last])
        em.mark('header 2 and back')

        mid, root_last, win = to_mid()
        self.correct(mid + [root_last], held)
        em.mark('to the midstate a third time')
        for reg, value in zip(mid, iv):
            self.add_constant(value, reg, subtract=True)
        mid = self.rounds_backward(win, mid, 'header 1', late=(9, iv[0]))
        self.drop_iv_state(mid)
        root = self.drop_header1_window(win) + [root_last]
        em.mark('undo header 1')

        em.adder = 'lean'  # The root is held next to this pass.
        inner1 = self.coinbase()
        em.adder = 'wide'
        self.add_classical(first_midstate, inner1[0])
        win = list(inner1) + self.padding(PAD256)
        self.expand(win, 63)
        self.correct(win, windows['root'])
        for reg, value in zip(root[1:], iv[1:]):
            self.add_constant(value, reg, subtract=True)
        inner1 = self.digest_backward(root, win, first_midstate, 'root')
        em.mark('undo root')

        self.uncoinbase(inner1)
        em.mark('undo coinbase')

        em.flush()
        header, register = [], 0
        for name, qubits in (('extranonce', self.extranonce), ('nonce', self.nonce)):
            header += [f'APPEND_TO_REGISTER q{q} r{register}' for q in qubits] + [f'REGISTER r{register} "{name}"']
            register += 1
        for name, _ in CLASSICAL:
            header += [f'APPEND_TO_REGISTER b{b} r{register}' for b in self.bit[name]] + [f'REGISTER r{register} "{name}"']
            register += 1
        return km.Circuit('\n'.join(header + em.chunks))


def report(builder: Builder) -> None:
    last = 0
    for label, count, depth, qubits in builder.em.marks:
        print(f'  {label:<16} {count - last:>10,} operations   depth {depth:>5}   qubits {qubits}', file=sys.stderr)
        last = count


def main() -> None:
    # The same circuit without resets: a reset would hide scratch that was not cleared.
    reference.check(Builder(resets=False).build())
    builder = Builder()
    circuit = builder.build()
    report(builder)
    reference.check(circuit)
    path = _HERE / 'circuit.kmb'
    circuit.to_file(path, format='kmb')
    stats = circuit.operation_statistics()
    print(f'Wrote {path.name}: {circuit.num_qubits} qubits, reaction depth {circuit.reaction_depth()}, '
          f'{stats.num_toffoli_like} Toffolis, {len(circuit)} operations, {path.stat().st_size} bytes. '
          f'Matches hashlib on 1024 made-up blocks.')


if __name__ == '__main__':
    main()
