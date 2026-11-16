"""Builds a low-reaction-depth SHA-256 compression circuit for `sha256-compress-v1`.

Written for the reaction-depth track (qubits x reaction depth). It starts from the ideas of
`../carry-lookahead-rounds` (log-depth adders, values kept as polynomials over qubits, fresh
registers for the new state words) and removes most of what that circuit holds in qubits or
waits for:

- Nothing but carries is ever stored. A sum of several terms is reduced to two rows by
  carry-save steps whose carry rows are never written down: a bit of such a row is built in
  helper qubits when a gate needs it and unbuilt straight after, also when rows are nested.
- A register that a round drops is cleared by subtracting a recomputation of its value in
  place. No measurement, no extra register, and one reaction less than measuring it and
  fixing the phase on a fresh copy.
- The adder's prefix network is aligned so that no carry is merged more than four times:
  AND-depth 5 for a 32-bit addition, and 5 reactions per step when the schedule is rewound.
- The adder works on the word in two parts and keeps a single carry between them, erased at
  the end by computing the lower carries once more. With a product of eight propagate bits
  held in one qubit, it needs 26 scratch qubits, not 46.
- The last two schedule words are never formed. Their terms go into the sums of rounds 62
  and 63, one of them as a row of its own, which saves one step of the rewind.
- When the schedule is rewound, the term that the next step depends on is subtracted in
  place and the other two leave through a fresh register, so their phase corrections do not
  pile up on one register.

Usage, from this directory:

    uv run --project ../../sha256_verifier python build.py
"""

from __future__ import annotations

import importlib.util
import pathlib

import kickmix as km

_spec = importlib.util.spec_from_file_location(
    'baseline_build', pathlib.Path(__file__).parent.parent / 'example' / 'build.py')
baseline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(baseline)

WORD, K, IV = baseline.WORD, baseline.K, baseline.IV
MASK = (1 << WORD) - 1
BIG_SIGMA0, BIG_SIGMA1 = baseline.BIG_SIGMA0, baseline.BIG_SIGMA1
SMALL_SIGMA0, SMALL_SIGMA1 = baseline.SMALL_SIGMA0, baseline.SMALL_SIGMA1

SPLIT = 15        # The adder handles bits below and from this position separately.
HELD = 8          # Propagate bits whose product the upper part holds in one qubit.
UNSTORED = 2      # Schedule words at the end that are never formed.
AHEAD = 2         # The schedule runs this many words ahead of the rounds.
FULL_UNDO = (16, 17)  # Rewind steps whose three terms all leave through a fresh register.


# ---- gate emitter ------------------------------------------------------------------------

class Emitter:
    """Emits Kickmix text and tracks reaction depth as Kickmix computes it, so that sums can
    be shaped by when each value is ready. Holds a pool of scratch qubits."""

    def __init__(self, first_free: int, extra_free: list[int], resets: bool = True) -> None:
        self.ops: list[str] = []
        self.xd: dict[int, int] = {}
        self.zd: dict[int, int] = {}
        self.bit_depth: dict[str, int] = {}
        self.free = list(extra_free)
        self.next = first_free
        self.resets = resets  # False only for a debug build that checks scratch is really clean.

    def alloc(self, n: int) -> list[int]:
        out = []
        for _ in range(n):
            if self.free:
                self.free.sort(reverse=True)
                out.append(self.free.pop())
            else:
                out.append(self.next)
                self.next += 1
        return out

    def release(self, qubits: list[int], *, reset: bool = True) -> None:
        """Returns qubits that are back at zero. Resetting them clears their depth."""
        for q in qubits:
            if reset:
                self.r(q)
            self.free.append(q)

    def x_depth(self, q: int) -> int:
        return self.xd.get(q, 0)

    def _bump(self, table: dict[int, int], q: int, d: int) -> None:
        if d > table.get(q, 0):
            table[q] = d

    def x(self, q: int) -> None:
        self.ops.append(f'X q{q}')

    def cx(self, c: int, t: int) -> None:
        self.ops.append(f'CX q{c} q{t}')
        self._bump(self.xd, t, self.xd.get(c, 0))
        self._bump(self.zd, c, self.zd.get(t, 0))

    def swap(self, a: int, b: int) -> None:
        self.ops.append(f'SWAP q{a} q{b}')
        self.xd[a], self.xd[b] = self.xd.get(b, 0), self.xd.get(a, 0)
        self.zd[a], self.zd[b] = self.zd.get(b, 0), self.zd.get(a, 0)

    def cz_if(self, a: int, b: int, bit: str) -> None:
        self.ops.append(f'CZ q{a} q{b} if {bit}')
        d = self.bit_depth[bit]
        self._bump(self.zd, a, max(d, self.xd.get(b, 0)))
        self._bump(self.zd, b, max(d, self.xd.get(a, 0)))

    def ccx(self, a: int, b: int, t: int) -> None:
        self.ops.append(f'CCX q{a} q{b} q{t}')
        xa, xb, zt = self.xd.get(a, 0), self.xd.get(b, 0), self.zd.get(t, 0)
        self._bump(self.xd, t, max(xa, xb) + 1)
        self._bump(self.zd, a, max(zt, xb) + 1)
        self._bump(self.zd, b, max(zt, xa) + 1)

    def hmr(self, q: int, bit: str = 'b0') -> None:
        """Measures q in the X basis into `bit` and resets it. A phase correction must follow."""
        self.ops.append(f'HMR q{q} {bit}')
        self.bit_depth[bit] = self.zd.get(q, 0) + 1
        self.xd[q] = self.zd[q] = 0

    def r(self, q: int) -> None:
        if self.resets:
            self.ops.append(f'R q{q}')
            self.xd[q] = self.zd[q] = 0


# ---- polynomial rows (as in carry-lookahead-rounds) --------------------------------------

def _mono(m) -> frozenset:
    return m if isinstance(m, frozenset) else frozenset([m])


class Poly:
    """A 32-bit value that is not stored: bit k is an XOR of monomials (products of one or two
    qubits) and a constant bit."""

    def __init__(self, bits, const: int = 0) -> None:
        self.bits = [frozenset(_mono(m) for m in b) for b in bits]
        self.const = const & MASK

    @staticmethod
    def reg(qubits: list[int]) -> 'Poly':
        return Poly([[q] for q in qubits])

    @staticmethod
    def constant(value: int) -> 'Poly':
        return Poly([[] for _ in range(WORD)], value)

    def __xor__(self, other: 'Poly') -> 'Poly':
        return Poly([a ^ b for a, b in zip(self.bits, other.bits)], self.const ^ other.const)

    def bit(self, k: int):
        return self.bits[k], (self.const >> k) & 1

    def is_constant(self) -> bool:
        return not any(self.bits)

    def is_linear(self) -> bool:
        return all(len(m) == 1 for b in self.bits for m in b)

    def arrival(self, em: Emitter) -> int:
        """AND-depth at which every bit can be built."""
        return max((max(em.x_depth(q) for q in m) + len(m) - 1 for b in self.bits for m in b), default=0)


def as_poly(x) -> Poly:
    return x if isinstance(x, Poly) else Poly.reg(x)


def inv(x) -> Poly:
    """~x. Subtractions are written with it: y - x = ~(~y + x), and -x = ~x + 1."""
    return as_poly(x) ^ Poly.constant(MASK)


def xor_bit(em: Emitter, bit, target: int) -> None:
    """target ^= bit, for a polynomial bit given as (monomials, constant)."""
    monomials, const = bit
    for m in sorted(monomials, key=lambda m: sorted(m)):
        m = sorted(m)
        if len(m) == 1:
            em.cx(m[0], target)
        else:
            em.ccx(m[0], m[1], target)
    if const:
        em.x(target)


class Held:
    """A qubit holding a polynomial bit for one Toffoli: a transient one unless the bit is
    already a single qubit."""

    def __init__(self, em: Emitter, bit) -> None:
        self.em, self.bit, self.t = em, bit, None

    def __enter__(self) -> int:
        monomials, const = self.bit
        if len(monomials) == 1 and not const:
            (m,) = monomials
            if len(m) == 1:
                return next(iter(m))
        self.t = self.em.alloc(1)[0]
        xor_bit(self.em, self.bit, self.t)
        return self.t

    def __exit__(self, *exc) -> None:
        if self.t is not None:
            xor_bit(self.em, self.bit, self.t)
            self.em.release([self.t])


def and_into(em: Emitter, x, y, target: int) -> None:
    """target ^= x & y for polynomial bits."""
    (xm, xc), (ym, yc) = x, y
    if (not xm and not xc) or (not ym and not yc):
        return
    if not xm:  # x is the constant 1
        xor_bit(em, y, target)
        return
    if not ym:
        xor_bit(em, x, target)
        return
    if xm == ym:  # y is x or ~x
        if xc == yc:
            xor_bit(em, x, target)
        return
    with Held(em, x) as a, Held(em, y) as b:
        em.ccx(a, b, target)


def _linear_bit(p: Poly, k: int):
    return {next(iter(m)) for m in p.bits[k]}, (p.const >> k) & 1


def _product(x, y):
    """Monomials and constant of the product of two linear bits."""
    (xs, xc), (ys, yc) = x, y
    out = set()
    for p in xs:
        for q in ys:
            out ^= {frozenset((p, q))}
    if yc:
        for p in xs:
            out ^= {frozenset((p,))}
    if xc:
        for q in ys:
            out ^= {frozenset((q,))}
    return out, xc & yc


def _quadratic(x: Poly, y: Poly, z: Poly, pairs, linear, shift: int = 0) -> Poly:
    """Sum of products of pairs of linear Polys, plus linear terms, bit by bit."""
    bits, const = [set() for _ in range(shift)], 0
    for k in range(WORD - shift):
        terms = {'x': x, 'y': y, 'z': z}
        m, c = set(), 0
        for u, v in pairs:
            mm, cc = _product(_linear_bit(terms[u], k), _linear_bit(terms[v], k))
            m ^= mm
            c ^= cc
        for u in linear:
            us, uc = _linear_bit(terms[u], k)
            m ^= {frozenset((q,)) for q in us}
            c ^= uc
        bits.append(m)
        const |= c << (k + shift)
    return Poly(bits, const)


def sigma(x, spec) -> Poly:
    """A rotate/shift XOR function of a linear value."""
    x = as_poly(x)
    rotations, shift = spec
    bits, const = [], 0
    for k in range(WORD):
        sources = [(k + r) % WORD for r in rotations]
        if shift is not None and k + shift < WORD:
            sources.append(k + shift)
        s, c = set(), 0
        for j in sources:
            s ^= set(x.bits[j])
            c ^= (x.const >> j) & 1
        bits.append(s)
        const |= c << k
    return Poly(bits, const)


def ch(e, f, g) -> Poly:
    """Ch(e, f, g) = ef ^ eg ^ g."""
    return _quadratic(as_poly(e), as_poly(f), as_poly(g), [('x', 'y'), ('x', 'z')], ['z'])


def maj(a, b, c, shift: int = 0) -> Poly:
    """Maj(a, b, c) = ab ^ ac ^ bc."""
    return _quadratic(as_poly(a), as_poly(b), as_poly(c), [('x', 'y'), ('x', 'z'), ('y', 'z')], [], shift)


# ---- rows that are not polynomials -------------------------------------------------------

class MajRow:
    """The carry row of a carry-save step, never stored: bit 0 is `cin`, and bit k + 1 is
    Maj(x_k, y_k, z_k) = ((x ^ z) & (y ^ z)) ^ z. The three rows may be of any kind."""

    def __init__(self, x, y, z, cin: int = 0) -> None:
        self.x, self.y, self.z, self.cin = x, y, z, cin

    def arrival(self, em: Emitter) -> int:
        return max(r.arrival(em) for r in (self.x, self.y, self.z)) + 1


class XorRow:
    """The XOR of rows, at least one of which is not a polynomial."""

    def __init__(self, rows) -> None:
        self.rows = list(rows)

    def arrival(self, em: Emitter) -> int:
        return max(r.arrival(em) for r in self.rows)


def nesting(row) -> int:
    """How many carry rows are nested inside one another in `row`."""
    if isinstance(row, Poly):
        return 0
    if isinstance(row, XorRow):
        return max(nesting(r) for r in row.rows)
    return 1 + max(nesting(r) for r in (row.x, row.y, row.z))


def row_xor_into(em: Emitter, row, k: int, target: int) -> None:
    """target ^= bit k of row."""
    if isinstance(row, Poly):
        xor_bit(em, row.bit(k), target)
    elif isinstance(row, XorRow):
        for r in row.rows:
            row_xor_into(em, r, k, target)
    elif k == 0:
        if row.cin:
            em.x(target)
    else:
        j = k - 1
        and_rows_into(em, [(row.x, j), (row.z, j)], [(row.y, j), (row.z, j)], target)
        row_xor_into(em, row.z, j, target)


def _poly_bits(items):
    """The XOR of row bits as one polynomial bit, or None if a row is not a polynomial."""
    m, c = frozenset(), 0
    for row, k in items:
        if not isinstance(row, Poly):
            return None
        mm, cc = row.bit(k)
        m, c = m ^ mm, c ^ cc
    return m, c


class HoldBits:
    """A qubit holding the XOR of several row bits, for one Toffoli."""

    def __init__(self, em: Emitter, items) -> None:
        self.em, self.items, self.t, self.inner = em, items, None, None

    def __enter__(self) -> int:
        bit = _poly_bits(self.items)
        if bit is not None:
            self.inner = Held(self.em, bit)
            return self.inner.__enter__()
        self.t = self.em.alloc(1)[0]
        for row, k in self.items:
            row_xor_into(self.em, row, k, self.t)
        return self.t

    def __exit__(self, *exc) -> None:
        if self.inner is not None:
            self.inner.__exit__(*exc)
            return
        for row, k in reversed(self.items):
            row_xor_into(self.em, row, k, self.t)
        self.em.release([self.t])


def and_rows_into(em: Emitter, a_items, b_items, target: int) -> None:
    """target ^= (XOR of the bits in a_items) & (XOR of the bits in b_items)."""
    a, b = _poly_bits(a_items), _poly_bits(b_items)
    if a is not None and b is not None:
        and_into(em, a, b, target)
        return
    for bit in (a, b):
        if bit is not None and not bit[0] and not bit[1]:
            return  # A known zero.
    with HoldBits(em, a_items) as qa, HoldBits(em, b_items) as qb:
        em.ccx(qa, qb, target)


# ---- carry-lookahead adder ---------------------------------------------------------------

def sklansky(lo: int, hi: int) -> list[list[tuple[int, int]]]:
    """Prefix steps by level for the carries out of bits lo .. hi - 1: (i, j) means
    G[i] ^= P(j+1 .. i) & G[j]. Bit i sits at index i + 1 of a 32-wide grid whose index 0 is
    empty, so no carry is merged more than four times."""
    levels = []
    for level in range(5):
        steps = []
        for index in range(1, WORD):
            if (index >> level) & 1:
                i, j = index - 1, ((index >> level) << level) - 2
                if lo <= j and i < hi:
                    steps.append((i, j))
        levels.append(steps)
    return levels


def _and_tree(em: Emitter, qubits: list[int]):
    """AND of `qubits` in transient qubits, as a balanced tree. Returns (top, levels)."""
    levels, layer = [], list(qubits)
    while len(layer) > 1:
        level, nxt = [], []
        for i in range(0, len(layer) - 1, 2):
            t = em.alloc(1)[0]
            em.ccx(layer[i], layer[i + 1], t)
            level.append((layer[i], layer[i + 1], t))
            nxt.append(t)
        if len(layer) % 2:
            nxt.append(layer[-1])
        levels.append(level)
        layer = nxt
    return layer[0], levels


def _measure_away(em: Emitter, levels) -> None:
    for level in reversed(levels):
        for a, b, t in reversed(level):
            em.hmr(t)
            em.cz_if(a, b, 'b0')
            em.release([t], reset=False)


class Product:
    """The AND of several qubits, held in one qubit. The tree under it is measured away at
    once and built again when the product itself is to be cleared."""

    def __init__(self, em: Emitter, qubits: list[int]) -> None:
        self.em, self.qubits = em, list(qubits)
        self.top, levels = _and_tree(em, self.qubits)
        _measure_away(em, levels[:-1])

    def clear(self) -> None:
        em, half = self.em, len(self.qubits) // 2
        left, left_levels = _and_tree(em, self.qubits[:half])
        right, right_levels = _and_tree(em, self.qubits[half:])
        _measure_away(em, [[(left, right, self.top)]])
        _measure_away(em, right_levels)
        _measure_away(em, left_levels)


def _prefix(em: Emitter, g, p: list[int], levels, inverse: bool) -> None:
    """Runs prefix steps on the carries g (a map from bit position to qubit)."""
    order = levels[::-1] if inverse else levels
    for steps in order:
        for i, j in sorted(steps, reverse=not inverse):
            top, built = _and_tree(em, [p[k] for k in range(j + 1, i + 1)])
            em.ccx(top, g[j], g[i])
            _measure_away(em, built)


def _merge_carry_in(em: Emitter, g, p: list[int], k: int, lo: int, hi: int, inverse: bool) -> None:
    """G[i] ^= P(lo .. i) & k for the carries of bits lo .. hi - 1, where k is the carry into
    bit lo. Products over more than HELD bits go through one held product of HELD bits."""
    cut = lo + HELD
    held = None
    for i in (reversed(range(lo, hi)) if inverse else range(lo, hi)):
        if i < cut:
            if held is not None:
                held.clear()
                held = None
            top, built = _and_tree(em, p[lo:i + 1])
            em.ccx(top, k, g[i])
            _measure_away(em, built)
        else:
            if held is None:
                held = Product(em, p[lo:cut])
            sub, built = _and_tree(em, p[cut:i + 1])
            t = em.alloc(1)[0]
            em.ccx(sub, held.top, t)  # The held product joins at the root.
            em.ccx(t, k, g[i])
            _measure_away(em, [[(sub, held.top, t)]])
            _measure_away(em, built)
    if held is not None:
        held.clear()


def add(em: Emitter, a, b: list[int], first=None) -> None:
    """`b += a` modulo 2^32 in place, with AND-depth 5. `a` is a row and is left unchanged.
    With `first`, b starts at zero and ends as first + a.

    The carries come from a Sklansky prefix network, are XORed into b, and are then erased:
    since carries(a, b) == carries(a, ~s) for s = a + b (Draper), running the network
    backwards on (a, ~s) turns them back into a & ~s. The word is done in two parts, bits
    below SPLIT and the rest, and only the carry into bit SPLIT is kept in between. That
    carry is erased last, by computing the lower carries from (a, ~s) once more.
    """
    n = len(b)
    b_row = Poly.reg(b)

    def constant(i: int) -> bool:
        return isinstance(a, Poly) and not a.bits[i]

    def take(lo: int, hi: int, g) -> None:
        """g[i] ^= a_i & b_i, then b_i ^= a_i, with one build of each bit of a."""
        for i in range(lo, hi):
            if constant(i):
                and_rows_into(em, [(a, i)], [(b_row, i)], g[i])
                row_xor_into(em, a, i, b[i])
            else:
                with HoldBits(em, [(a, i)]) as q:
                    em.ccx(q, b[i], g[i])
                    em.cx(q, b[i])

    def give(lo: int, hi: int, g) -> None:
        """The inverse of `take`."""
        for i in range(lo, hi):
            if constant(i):
                row_xor_into(em, a, i, b[i])
                and_rows_into(em, [(a, i)], [(b_row, i)], g[i])
            else:
                with HoldBits(em, [(a, i)]) as q:
                    em.cx(q, b[i])
                    em.ccx(q, b[i], g[i])

    def xor_a(lo: int, hi: int) -> None:
        for i in range(lo, hi):
            row_xor_into(em, a, i, b[i])

    def flip(lo: int, hi: int) -> None:
        for i in range(lo, hi):
            em.x(b[i])

    if first is not None:
        for i in range(n):
            row_xor_into(em, first, i, b[i])
    carry = em.alloc(1)[0]
    for lo, hi in ((0, SPLIT), (SPLIT, n - 1)):
        end = n if hi == n - 1 else hi  # The top bit takes a carry and gives none.
        g = dict(zip(range(lo, hi), em.alloc(hi - lo)))
        levels = sklansky(lo, hi)
        take(lo, hi, g)  # b = a ^ b: the propagates.
        xor_a(hi, end)
        _prefix(em, g, b, levels, inverse=False)
        if lo:
            _merge_carry_in(em, g, b, carry, lo, hi, inverse=False)
            em.cx(carry, b[lo])
        else:
            em.cx(g[hi - 1], carry)  # The carry into bit SPLIT; it goes into b later.
        for i in range(lo, hi):
            if i + 1 < end:
                em.cx(g[i], b[i + 1])  # b = s.
        flip(lo, hi)
        xor_a(lo, hi)  # b = a ^ ~s.
        if lo:
            _merge_carry_in(em, g, b, carry, lo, hi, inverse=True)
        _prefix(em, g, b, levels, inverse=True)  # g[i] = a_i & ~s_i.
        give(lo, hi, g)
        flip(lo, hi)
        em.release(list(g.values()))
    lo, hi = 0, SPLIT
    g = dict(zip(range(lo, hi), em.alloc(hi - lo)))
    levels = sklansky(lo, hi)
    flip(lo, hi)
    take(lo, hi, g)
    _prefix(em, g, b, levels, inverse=False)
    em.cx(g[hi - 1], carry)
    em.release([carry])
    _prefix(em, g, b, levels, inverse=True)
    give(lo, hi, g)
    flip(lo, hi)
    em.release(list(g.values()))


def subtract(em: Emitter, a, b: list[int]) -> None:
    """`b -= a`: b - a = ~(~b + a)."""
    for q in b:
        em.x(q)
    add(em, a, b)
    for q in b:
        em.x(q)


# ---- sums --------------------------------------------------------------------------------

def two_rows(em: Emitter, terms, const: int = 0, cin: int = 0, tail: int | None = None):
    """Reduces sum(terms) + const + cin to two rows, storing nothing. `cin` is 0 or 1.

    The last `tail` terms are added one at a time at the end, so the last one is outermost:
    it has the fewest gates between it and the result. With tail=None those are the terms
    that are ready last. The other terms are reduced first, in as few nested levels as
    possible. A carry-save step of three XOR-linear rows gives a degree-2 polynomial; any
    other step gives a `MajRow`. The carry-in goes into the free low bit of a carry row.
    """
    rows = []
    for p in terms:
        p = p if isinstance(p, (Poly, MajRow, XorRow)) else as_poly(p)
        if isinstance(p, Poly) and p.is_constant():
            const += p.const
        else:
            rows.append(p)
    if cin and (const & MASK or len(rows) < 3):
        const, cin = const + cin, 0
    const &= MASK
    if tail is None:
        latest = max((p.arrival(em) for p in rows), default=0)
        outer = sorted((p for p in rows if p.arrival(em) >= latest - 1), key=lambda p: p.arrival(em))
        inner = [p for p in rows if p.arrival(em) < latest - 1]
    else:
        inner, outer = rows[:len(rows) - tail], rows[len(rows) - tail:]
    if const:
        inner.insert(0, Poly.constant(const))

    def combine(x, y, z):
        nonlocal cin
        if all(isinstance(r, Poly) and r.is_linear() for r in (x, y, z)):
            carry = maj(x, y, z, shift=1) ^ Poly.constant(cin)
        else:
            carry = MajRow(x, y, z, cin)
        cin = 0
        total = x ^ y ^ z if all(isinstance(r, Poly) for r in (x, y, z)) else XorRow([x, y, z])
        return [total, carry]

    while len(inner) > 2:
        linear = [p for p in inner if isinstance(p, Poly) and p.is_linear()]
        if len(linear) >= 3:
            three = sorted(linear, key=lambda p: p.arrival(em))[:3]
        else:
            three = sorted(inner, key=nesting)[:3]
        inner = [p for p in inner if not any(p is q for q in three)] + combine(*three)
    rows = inner
    for p in outer:
        rows.append(p)
        if len(rows) > 2:
            rows = combine(*rows)
    assert not cin, 'no carry row to take the carry-in'
    while len(rows) < 2:
        rows.append(Poly.constant(0))
    rows.sort(key=lambda r: not isinstance(r, Poly))  # A polynomial, if any, is the adder's operand.
    operand, first = rows
    return first, operand


def _is_zero(row) -> bool:
    return isinstance(row, Poly) and row.is_constant() and not row.const


def create(em: Emitter, terms, const: int = 0, cin: int = 0) -> list[int]:
    """A fresh register holding (sum(terms) + const + cin) mod 2^32."""
    first, operand = two_rows(em, terms, const, cin)
    out = em.alloc(WORD)
    if _is_zero(operand):
        for k in range(WORD):
            row_xor_into(em, first, k, out[k])
    else:
        add(em, operand, out, first=first)
    return out


def clear(em: Emitter, reg: list[int], terms, const: int = 0, cin: int = 0, tail: int = 0) -> None:
    """Clears and frees `reg`, which holds sum(terms) + const + cin: subtracts one row in
    place and XORs the other away."""
    first, operand = two_rows(em, terms, const, cin, tail)
    if not _is_zero(operand):
        subtract(em, operand, reg)
    for k in range(WORD):
        row_xor_into(em, first, k, reg[k])
    em.release(reg)


# ---- SHA-256 -----------------------------------------------------------------------------

class Builder:
    def __init__(self, resets: bool = True) -> None:
        # The digest qubits start at zero and are used as scratch; the result goes wherever
        # the last round leaves it, and the digest register is declared there.
        self.em = Emitter(768, list(range(512, 768)), resets)
        self.w = [list(range(WORD * j, WORD * (j + 1))) for j in range(16)]
        self.stored = 64 - UNSTORED  # Schedule words from here on are never formed.

    def schedule_terms(self, t: int):
        """W_t - W_(t-16) as rows: sigma0(W_(t-15)), W_(t-7), sigma1(W_(t-2))."""
        return (sigma(self.w[(t - 15) % 16], SMALL_SIGMA0), Poly.reg(self.w[(t - 7) % 16]),
                sigma(self.w[(t - 2) % 16], SMALL_SIGMA1))

    def schedule(self, t: int) -> None:
        """Turns W_(t-16) into W_t in place, the term that is ready last going last."""
        for term in self.schedule_terms(t):
            add(self.em, term, self.w[t % 16])

    def unschedule(self, t: int) -> None:
        """Turns W_t back into W_(t-16).

        Phase corrections flow from a register that is added into to the operand, and the
        next step is the one that has W_(t-2) as its target. So sigma1(W_(t-2)) is subtracted
        first and in place. The other two terms leave through a fresh register: it takes the
        value W_(t-16), and the old register is cleared against it. In the last steps of the
        chain all three terms go that way.
        """
        em = self.em
        target = self.w[t % 16]
        s0, middle, s1 = self.schedule_terms(t)
        rest = [s1, middle, s0] if t in FULL_UNDO else [middle, s0]
        if t not in FULL_UNDO:
            subtract(em, s1, target)
        fresh = create(em, [inv(target)] + rest)  # ~(~T + ...) = T - ...
        for q in fresh:
            em.x(q)
        clear(em, target, [fresh] + rest)
        self.w[t % 16] = fresh

    def folded_terms(self, t: int):
        s0, middle, _ = self.schedule_terms(t)
        return [s0, middle, Poly.constant(K[t])]

    def fold(self, t: int) -> None:
        """For a word that is never formed: turns the register of W_(t-16) into
        W_t + K_t - sigma1(W_(t-2)) in place. The missing term is the one the rewind
        starts from; round t takes it as a row of its own."""
        for term in self.folded_terms(t):
            add(self.em, term, self.w[t % 16])

    def unfold(self, t: int) -> None:
        """Undoes `fold`. Three subtractions in a row would stack their phase corrections on
        a register that the rewind still has to turn into a block word, so the terms leave
        through a fresh register instead, as in `unschedule`."""
        em, slot, terms = self.em, self.w[t % 16], self.folded_terms(t)
        fresh = create(em, [inv(slot)] + terms)  # ~(~Y + ...) = Y - ...
        for q in fresh:
            em.x(q)
        clear(em, slot, [fresh] + terms)
        self.w[t % 16] = fresh

    def round(self, t: int, state: list) -> list:
        """One round. State words are registers, or constant Polys in the first rounds.

        Two sums into fresh registers, and two registers cleared by subtraction:

            e' = d + h + K + W + Sigma1(e) + Ch(e, f, g)          h = e' - (the rest)
            a' = e' - d + Sigma0(a) + Maj(a, b, c)                d = e' - a' + (the rest)

        In the subtractions the term that holds the register cleared next round (g in Ch, c
        in Maj) is outermost: its phase corrections then come 7 reactions after those of the
        cleared register, which is the AND-depth of a round, so they never run ahead of it.
        """
        em = self.em
        a, b, c, d, e, f, g, h = state
        s1, chv = sigma(e, BIG_SIGMA1), ch(e, f, g)
        s0, mj = sigma(a, BIG_SIGMA0), maj(a, b, c)
        slot = self.w[t % 16]
        if not isinstance(h, list):  # Rounds 0 to 3: d and h are constants.
            e_new = create(em, [slot, d, h, s1, chv], K[t])
        else:
            # K_t goes into the register of W_t in place for the round, which saves a level
            # of nested carry rows. For the last words `fold` has done that already, and
            # has left out one term, which is a row of its own here.
            last = t >= self.stored
            head = [self.schedule_terms(t)[2]] if last else []
            if not last:
                add(em, Poly.constant(K[t]), slot)
            e_new = create(em, [slot] + head + [d, h, s1, chv])
            for q in h:  # h = ~(~e' + d + K + W + Sigma1 + Ch)
                em.x(q)
            if t == 63:    # Nothing is cleared after this round: the head goes outermost.
                clear(em, h, [slot, d, s1, inv(e_new), chv] + head, tail=2)
            elif t == 62:  # Likewise, but Ch stays outermost for round 63.
                clear(em, h, [slot, d, s1, inv(e_new)] + head + [chv], tail=2)
            else:
                clear(em, h, [slot, d, s1, inv(e_new), chv], tail=1)
            if not last:
                subtract(em, Poly.constant(K[t]), slot)

        a_new = create(em, [e_new, inv(d), s0, mj], cin=1)
        if isinstance(d, list):
            clear(em, d, [e_new, inv(a_new), s0, mj], cin=1, tail=1)
        return [a_new, a, b, c, e_new, e, f, g]

    def build(self) -> km.Circuit:
        em = self.em
        state = [Poly.constant(v) for v in IV]
        formed = 15
        for t in range(64):
            # W_(t+2) is formed before round t adds K_t into the register of W_t and takes
            # it out again, which would otherwise delay the schedule.
            while formed < min(t + AHEAD, self.stored - 1):
                formed += 1
                self.schedule(formed)
            if t == self.stored:
                # Fold all the unformed words now, before a round disturbs their registers;
                # fold(t + 1) changes a register that fold(t) reads, hence the order.
                for u in range(self.stored, 64):
                    self.fold(u)
            state = self.round(t, state)
        for u in reversed(range(self.stored, 64)):
            self.unfold(u)
        for j in range(8):  # Feed-forward.
            add(em, Poly.constant(IV[j]), state[j])
        for t in reversed(range(16, self.stored)):  # Restore the block.
            self.unschedule(t)
        self.bring_home(state)

        header = [f'APPEND_TO_REGISTER q{q} r0' for q in range(512)] + ['REGISTER r0 "block"']
        header += [f'APPEND_TO_REGISTER q{q} r1' for reg in state for q in reg] + ['REGISTER r1 "digest"']
        return km.Circuit('\n'.join(header + em.ops))

    def bring_home(self, state: list) -> None:
        """Swaps the block words back to qubits 0 .. 511; the rewind left them elsewhere."""
        where = {q: (reg, k) for reg in self.w + state for k, q in enumerate(reg)}
        for j in range(16):
            for k in range(WORD):
                home, now = WORD * j + k, self.w[j][k]
                if now == home:
                    continue
                self.em.swap(now, home)
                other = where.pop(home, None)
                self.w[j][k] = home
                where[home] = (self.w[j], k)
                if other is not None:
                    other[0][other[1]] = now
                    where[now] = other
                else:
                    where.pop(now, None)


def main() -> None:
    # The same circuit without resets: a reset would hide scratch that was not cleared.
    baseline.check(Builder(resets=False).build())
    circuit = Builder().build()
    baseline.check(circuit)
    path = pathlib.Path(__file__).with_name('circuit.kmb')
    circuit.to_file(path, format='kmb')
    stats = circuit.operation_statistics()
    print(f'Wrote {path.name}: {circuit.num_qubits} qubits, reaction depth {circuit.reaction_depth()}, '
          f'{stats.num_toffoli_like} Toffolis, {len(circuit)} operations, {path.stat().st_size} bytes. '
          f'Matches hashlib on 1024 messages.')


if __name__ == '__main__':
    main()
