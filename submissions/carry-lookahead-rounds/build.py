"""Builds a low-reaction-depth SHA-256 compression circuit for `sha256-compress-v1`.

Written for the reaction-depth track (qubits x reaction depth). There, Toffolis cost nothing,
so this circuit spends them freely to shorten the two chains Kickmix's reaction depth tracks:
the AND-depth of every value (x), and the chain of phase corrections that measurement-based
uncomputation leaves behind (z).

- Every addition is a log-depth carry-lookahead adder (Sklansky prefix), AND-depth 6 instead
  of 31 for a ripple adder. Its carries are erased with Draper's identity
  carries(a, b) == carries(a, ~(a + b)), and each group propagate is built from transient
  qubits when it is needed and unbuilt at once.
- Each round computes e' and a' into fresh registers as one carry-save sum each. XOR-linear
  terms (Sigma, sums of the carry-save tree, constants) and degree-2 terms (Ch, Maj, and
  carries of early linear terms) are never stored: a qubit is built from them only for the
  Toffoli that needs it, then unbuilt and reset. Only carry rows are stored.
- The state registers are never added into in place. In-place additions turn the target's
  depth into phase-correction depth on the operand, and that chains from round to round.
  Instead the two registers a round drops (d and h) are measured in the X basis, and the phase
  correction is applied to a fresh recomputation of their value from registers that remain:
  d = e' - a' + Sigma0(a) + Maj(a, b, c), h = a' - W - K - Sigma1(e) - Ch(e, f, g) - Sigma0(a) - Maj(a, b, c).
- A reset qubit carries no depth, so ancillas are reused freely: depth follows data, not wires.
- The message schedule is expanded in place over `block` and rewound, as in the baseline, but
  as three separate additions per word ordered to keep the phase chains short.
- In rounds 0 to 3, state words that are still known constants are kept as constants.

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

# A carry-save step whose inputs are all XOR-linear may keep its carry virtual (a degree-2
# polynomial) when its inputs arrive at least this many AND levels before the latest term.
SLACK_ROUND = 2
SLACK_ERASE = 0


# ---- gate emitter ------------------------------------------------------------------------

class Emitter:
    """Emits Kickmix text and tracks reaction depth as Kickmix computes it, so that carry-save
    trees can be shaped by when each value is ready. Holds a pool of scratch qubits."""

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

    def z_if(self, q: int, bit: str) -> None:
        self.ops.append(f'Z q{q} if {bit}')
        self._bump(self.zd, q, self.bit_depth[bit])

    def cx(self, c: int, t: int) -> None:
        self.ops.append(f'CX q{c} q{t}')
        self._bump(self.xd, t, self.xd.get(c, 0))
        self._bump(self.zd, c, self.zd.get(t, 0))

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


# ---- carry-lookahead adder ---------------------------------------------------------------

def sklansky(m: int) -> list[list[tuple[int, int]]]:
    """Prefix steps by level: (i, j) means G[i] ^= P(j+1 .. i) & G[j]."""
    levels, level = [], 0
    while (1 << level) < m:
        levels.append([(i, ((i >> level) << level) - 1) for i in range(m) if (i >> level) & 1])
        level += 1
    return levels


def _and_tree(em: Emitter, qubits: list[int]) -> tuple[int, list[tuple[int, int, int]]]:
    """AND of `qubits` in transient qubits, as a balanced tree. Returns (top, gates)."""
    built, layer = [], list(qubits)
    while len(layer) > 1:
        nxt = []
        for i in range(0, len(layer) - 1, 2):
            t = em.alloc(1)[0]
            em.ccx(layer[i], layer[i + 1], t)
            built.append((layer[i], layer[i + 1], t))
            nxt.append(t)
        if len(layer) % 2:
            nxt.append(layer[-1])
        layer = nxt
    return layer[0], built


def _unbuild(em: Emitter, built: list[tuple[int, int, int]]) -> None:
    for a, b, t in reversed(built):
        em.hmr(t)
        em.cz_if(a, b, 'b0')
        em.release([t], reset=False)


def _prefix(em: Emitter, g: list[int], p: list[int], levels, inverse: bool) -> None:
    order = list(enumerate(levels))
    for _, steps in (order[::-1] if inverse else order):
        for i, j in sorted(steps, reverse=not inverse):
            top, built = _and_tree(em, [p[k] for k in range(j + 1, i + 1)])
            em.ccx(top, g[j], g[i])
            _unbuild(em, built)


def add(em: Emitter, a: list[int], b: list[int]) -> None:
    """`b += a` modulo 2^n in place, with AND-depth 6 for n = 32. `a` is left unchanged.

    The carries are computed into n - 1 qubits by a Sklansky prefix network, XORed into b, and
    then erased: since carries(a, b) == carries(a, ~s) for s = a + b, running the prefix network
    backwards on (a, ~s) turns them back into a & ~s, which is cleared by measurement.
    """
    n = len(b)
    m = n - 1
    levels = sklansky(m)
    g = em.alloc(m)
    for i in range(m):
        em.ccx(a[i], b[i], g[i])
    for i in range(n):
        em.cx(a[i], b[i])  # b = a ^ b, the propagates
    _prefix(em, g, b, levels, inverse=False)  # g[i] = carry into bit i + 1
    for i in range(m):
        em.cx(g[i], b[i + 1])  # b = s
    for i in range(m):
        em.x(b[i])
        em.cx(a[i], b[i])  # b = a ^ ~s
    _prefix(em, g, b, levels, inverse=True)  # g[i] = a_i & ~s_i
    for i in range(m):
        em.cx(a[i], b[i])
        em.hmr(g[i])
        em.cz_if(a[i], b[i], 'b0')
        em.x(b[i])
    em.release(g, reset=False)


def subtract(em: Emitter, a: list[int], b: list[int]) -> None:
    """`b -= a`: b - a = ~(~b + a)."""
    for q in b:
        em.x(q)
    add(em, a, b)
    for q in b:
        em.x(q)


# ---- polynomial values -------------------------------------------------------------------

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

    def plain(self, k: int) -> bool:
        """Bit k is exactly one qubit."""
        return len(self.bits[k]) == 1 and len(next(iter(self.bits[k]))) == 1 and not (self.const >> k) & 1

    def arrival(self, em: Emitter) -> int:
        """AND-depth at which every bit can be built."""
        return max((max(em.x_depth(q) for q in m) + len(m) - 1 for b in self.bits for m in b), default=0)


def as_poly(x) -> Poly:
    return x if isinstance(x, Poly) else Poly.reg(x)


def negate(x) -> Poly:
    """~x, so that -x = ~x + 1."""
    return as_poly(x) ^ Poly.constant(MASK)


def _sorted(monomials):
    return sorted(monomials, key=lambda m: sorted(m))


def xor_bit(em: Emitter, bit, target: int) -> None:
    """target ^= bit, for a bit given as (monomials, constant)."""
    monomials, const = bit
    for m in _sorted(monomials):
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
    if xm == ym:  # x & y = x & (x ^ (y ^ x)), and y ^ x is a constant
        if xc == yc:
            xor_bit(em, x, target)
        elif not xc:  # y = ~x: x & ~x = 0
            pass
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


# ---- out-of-place sums -------------------------------------------------------------------

class Tape:
    """Reversible steps over values that stay put; `undo` replays them backwards and frees the
    qubits they allocated."""

    def __init__(self, em: Emitter) -> None:
        self.em, self.steps, self.temps = em, [], []

    def temp(self, n: int = WORD) -> list[int]:
        t = self.em.alloc(n)
        self.temps.append(t)
        return t

    def do(self, step) -> None:
        step()
        self.steps.append(step)

    def undo(self) -> None:
        for step in reversed(self.steps):
            step()
        for t in reversed(self.temps):
            self.em.release(t)
        self.steps, self.temps = [], []


def store_maj(tape: Tape, x: Poly, y: Poly, z: Poly) -> Poly:
    """A stored carry row: bit k + 1 = Maj(x_k, y_k, z_k) = ((x ^ z) & (y ^ z)) ^ z."""
    t = tape.temp()
    em = tape.em

    def step() -> None:
        for k in range(WORD - 1):
            (xm, xc), (ym, yc), (zm, zc) = x.bit(k), y.bit(k), z.bit(k)
            and_into(em, (xm ^ zm, xc ^ zc), (ym ^ zm, yc ^ zc), t[k + 1])
            xor_bit(em, (zm, zc), t[k + 1])

    tape.do(step)
    return Poly([[]] + [[t[k]] for k in range(1, WORD)])


def osum(tape: Tape, terms, const: int = 0, slack: int = SLACK_ROUND):
    """out := (sum of terms + const) mod 2^32 in a fresh register.

    The terms are reduced to two by carry-save steps, earliest first, and the two are added
    with the carry-lookahead adder. A carry of three early linear terms stays virtual; any other
    carry is stored on `tape`. Returns (out, how) for `unsum`.
    """
    em = tape.em
    rows = []
    for p in map(as_poly, terms):
        if p.is_constant():
            const += p.const
        else:
            rows.append(p)
    if const & MASK:
        rows.append(Poly.constant(const))
    while len(rows) > 2:
        rows.sort(key=lambda p: p.arrival(em))
        linear = [p for p in rows if p.is_linear()]
        latest = max(p.arrival(em) for p in rows)
        if len(linear) >= 3 and max(p.arrival(em) for p in linear[:3]) + slack <= latest:
            x, y, z = linear[:3]
            carry = maj(x, y, z, shift=1)
        else:
            x, y, z = rows[:3]
            carry = store_maj(tape, x, y, z)
        rows = [p for p in rows if p is not x and p is not y and p is not z] + [x ^ y ^ z, carry]

    out = em.alloc(WORD)
    first = rows[0]
    second = rows[1] if len(rows) > 1 else None
    addend = None
    if second is not None:
        def storable(p: Poly) -> bool:
            return all(p.plain(k) or (not p.bits[k] and not (p.const >> k) & 1) for k in range(WORD))
        if not storable(second) and storable(first):
            first, second = second, first
        if storable(second):  # Plain qubits, except bits known to be zero.
            zeros = [k for k in range(WORD) if not second.bits[k]]
            pad = iter(tape.temp(len(zeros))) if zeros else iter(())
            addend = [next(iter(next(iter(second.bits[k])))) if second.bits[k] else next(pad)
                      for k in range(WORD)]
        else:
            addend = tape.temp()
            tape.do(lambda: [xor_bit(em, second.bit(k), addend[k]) for k in range(WORD)])
    for k in range(WORD):
        xor_bit(em, first.bit(k), out[k])
    if addend is not None:
        add(em, addend, out)
    return out, (first, addend)


def unsum(em: Emitter, out: list[int], how) -> None:
    first, addend = how
    if addend is not None:
        subtract(em, addend, out)
    for k in range(WORD):
        xor_bit(em, first.bit(k), out[k])
    em.release(out)


# ---- SHA-256 -----------------------------------------------------------------------------

class Builder:
    def __init__(self, resets: bool = True) -> None:
        # The digest qubits start at zero and are used as scratch; the result goes wherever
        # the last round leaves it, and the digest register is declared there.
        self.em = Emitter(768, list(range(512, 768)), resets)
        self.w = [list(range(WORD * j, WORD * (j + 1))) for j in range(16)]

    def erase(self, reg: list[int], terms, const: int) -> None:
        """Clears `reg`, which holds sum(terms) + const of registers that remain: measures it in
        the X basis, then applies the phase correction to a fresh copy of its value."""
        em = self.em
        for i, q in enumerate(reg):
            em.hmr(q, f'b{i + 1}')
        em.release(reg, reset=False)
        tape = Tape(em)
        value, how = osum(tape, terms, const, slack=SLACK_ERASE)
        for i, q in enumerate(value):
            em.z_if(q, f'b{i + 1}')
        unsum(em, value, how)
        tape.undo()

    def schedule(self, t: int, *, undo: bool = False) -> None:
        """Turns W_(t-16) into W_t in place, or back: W_t = W_(t-16) + sigma0(W_(t-15)) + W_(t-7) + sigma1(W_(t-2)).

        Three additions. First comes the operand whose register is updated next (phase
        corrections flow from the target to the operand), last the one that is ready last.
        """
        em = self.em
        target = self.w[t % 16]
        s0 = (self.w[(t - 15) % 16], SMALL_SIGMA0)
        s1 = (self.w[(t - 2) % 16], SMALL_SIGMA1)
        middle = self.w[(t - 7) % 16]
        if undo:
            for q in target:
                em.x(q)
        for operand in ([s1, middle, s0] if undo else [s0, middle, s1]):
            if isinstance(operand, tuple):
                tape = Tape(em)
                held = tape.temp()
                value = sigma(*operand)
                tape.do(lambda held=held, value=value: [xor_bit(em, value.bit(k), held[k]) for k in range(WORD)])
                add(em, held, target)
                tape.undo()
            else:
                add(em, operand, target)
        if undo:
            for q in target:
                em.x(q)

    def round(self, t: int, state: list) -> list:
        """One round. State words are registers, or constant Polys in the first rounds."""
        a, b, c, d, e, f, g, h = state
        w = self.w[t % 16]
        s1, chv = sigma(e, BIG_SIGMA1), ch(e, f, g)
        s0, mj = sigma(a, BIG_SIGMA0), maj(a, b, c)

        tape = Tape(self.em)
        e_new, _ = osum(tape, [as_poly(d), as_poly(h), w, s1, chv], K[t])
        tape.undo()
        tape = Tape(self.em)
        a_new, _ = osum(tape, [as_poly(h), w, s1, chv, s0, mj], K[t])
        tape.undo()

        if not as_poly(d).is_constant():  # d = e' - a' + Sigma0(a) + Maj(a, b, c)
            self.erase(d, [e_new, negate(a_new), s0, mj], 1)
        if not as_poly(h).is_constant():  # h = a' - W - K - Sigma1(e) - Ch(e, f, g) - Sigma0(a) - Maj(a, b, c)
            self.erase(h, [a_new] + [negate(x) for x in (w, s1, chv, s0, mj)], (5 - K[t]) & MASK)
        return [a_new, a, b, c, e_new, e, f, g]

    def build(self) -> km.Circuit:
        state = [Poly.constant(v) for v in IV]
        for t in range(64):
            if t >= 16:
                self.schedule(t)
            state = self.round(t, state)
        for j in range(8):  # Feed-forward.
            tape = Tape(self.em)
            value = tape.temp()
            tape.do(lambda value=value, v=IV[j]: [self.em.x(value[k]) for k in range(WORD) if (v >> k) & 1])
            add(self.em, value, state[j])
            tape.undo()
        for t in reversed(range(16, 64)):  # Restore the block.
            self.schedule(t, undo=True)

        header = [f'APPEND_TO_REGISTER q{q} r0' for q in range(512)] + ['REGISTER r0 "block"']
        header += [f'APPEND_TO_REGISTER q{q} r1' for reg in state for q in reg] + ['REGISTER r1 "digest"']
        return km.Circuit('\n'.join(header + self.em.ops))


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
