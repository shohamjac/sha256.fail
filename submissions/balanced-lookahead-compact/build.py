"""Builds a SHA-256 compression circuit for `sha256-compress-v1` that is short on both
counts, reaction depth below 1,000 and fewer than 100,000 Toffolis, on as few qubits as I
could manage within those two limits.

It is `../balanced-lookahead-rounds` with its scratch cut down. As there, every AND is
computed into a qubit of its own and measured away, every value in between is an XOR of
register qubits and AND qubits, each round forms e' and a' in fresh registers, and the
registers it drops are measured in the X basis with the phase fixed on the bits of a second
sum. What is new:

- The carries of a sum that forms a register are built in place, in 31 qubits, and those
  qubits become the register: each takes the propagate of its bit. So a new register costs
  no qubits beyond its carries, and its carries are never uncomputed.
- A register that is dropped is measured before the sum that fixes its phase is computed,
  so its qubits are free during that sum. The measured bits wait.
- When a sum only fixes a phase, some of its carries are merged in place by a Toffoli and
  undone by a Toffoli. That trades Toffolis for qubits, as far as the limit allows.
- The two rows that a round's sums for e' and h share are held as one register and one
  carry row. The ANDs they were made from are measured away while the rows are in use and
  made again afterwards to take the rows apart.
- All carry trees are Brent-Kung networks, which have the fewest nodes, except in the
  clearing step of the rewind, where a Sklansky network keeps the chain short.

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

# The carry tree of each sum that fixes a phase, and how many of its merges are done in
# place with a Toffoli (each saves a qubit and costs a Toffoli). Sums that form a register
# use a Brent-Kung tree and are in place throughout, at no cost.
ROUND_CLEAR = ('brent-kung', 99)
SCHEDULE_CLEAR = ('brent-kung', 18)
REWIND_CLEAR = ('sklansky', 79)
FINAL_CLEAR = ('ripple', 0)


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

    def z_if(self, q: int, bit: str) -> None:
        self.ops.append(f'Z q{q} if {bit}')
        self._bump(self.zd, q, self.bit_depth[bit])

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


# ---- bits and rows -----------------------------------------------------------------------
#
# A bit is a pair (qubits, constant): the XOR of those qubits and the constant. A row is a
# list of 32 bits, a value that is not stored anywhere as such.

ZERO = (frozenset(), 0)


def xor(*bits):
    qubits, const = frozenset(), 0
    for q, c in bits:
        qubits, const = qubits ^ q, const ^ c
    return qubits, const


def register(qubits: list[int]):
    return [(frozenset([q]), 0) for q in qubits]


def constant(value: int):
    return [(frozenset(), (value >> k) & 1) for k in range(WORD)]


def as_row(x):
    return register(x) if isinstance(x[0], int) else x


def inv(x):
    """~x. Subtractions are written with it: y - x = ~(~y + x), and -x = ~x + 1."""
    return [(q, c ^ 1) for q, c in as_row(x)]


def xor_rows(*rows):
    return [xor(*(row[k] for row in rows)) for k in range(WORD)]


def arrival(em: Emitter, row) -> int:
    """AND-depth at which every bit of the row can be built."""
    return max((em.x_depth(q) for qubits, _ in row for q in qubits), default=0)


def sigma(x, spec):
    """A rotate/shift XOR function of a row."""
    x = as_row(x)
    rotations, shift = spec
    out = []
    for k in range(WORD):
        sources = [(k + r) % WORD for r in rotations]
        if shift is not None and k + shift < WORD:
            sources.append(k + shift)
        out.append(xor(*(x[j] for j in sources)))
    return out


def xor_into(em: Emitter, bit, target: int) -> None:
    """target ^= bit."""
    for q in sorted(bit[0]):
        em.cx(q, target)
    if bit[1]:
        em.x(target)


class Held:
    """A qubit holding a bit for one gate: a transient one unless the bit is a single qubit."""

    def __init__(self, em: Emitter, bit) -> None:
        self.em, self.bit, self.t = em, bit, None

    def __enter__(self) -> int:
        qubits, const = self.bit
        if len(qubits) == 1 and not const:
            return next(iter(qubits))
        self.t = self.em.alloc(1)[0]
        xor_into(self.em, self.bit, self.t)
        return self.t

    def __exit__(self, *exc) -> None:
        if self.t is not None:
            xor_into(self.em, self.bit, self.t)
            self.em.release([self.t])


class Tape:
    """ANDs, each computed into a qubit of its own, and XORs written into those qubits.
    `undo` takes them back in reverse order: an AND is measured in the X basis and its phase
    fixed by a CZ on its two inputs, which costs no Toffoli. A Toffoli written into a qubit
    in place is undone by the same Toffoli."""

    def __init__(self, em: Emitter) -> None:
        self.em, self.steps, self.made, self.last = em, [], set(), None

    def and_(self, x, y):
        """x & y as a bit. A new qubit is made unless the answer is plain from the inputs."""
        self.last = None
        (xq, xc), (yq, yc) = x, y
        if not xq:
            return y if xc else ZERO
        if not yq:
            return x if yc else ZERO
        if xq == yq:  # y is x or ~x
            return x if xc == yc else ZERO
        em = self.em
        t = em.alloc(1)[0]
        with Held(em, x) as a, Held(em, y) as b:
            em.ccx(a, b, t)
        self.steps.append(('and', t, x, y))
        self.made.add(t)
        self.last = t
        return frozenset([t]), 0

    def and_xor(self, x, y, z):
        """(x & y) ^ z as a bit, with z written into the AND's qubit when a new one is made.
        The bit is then a single qubit, which keeps later gates short."""
        bit = self.and_(x, y)
        if self.last is None or not z[0]:
            return xor(bit, z)
        self.write(z, self.last)
        return bit

    def write(self, bit, t: int) -> None:
        """t ^= bit, for a qubit t made on this tape."""
        xor_into(self.em, bit, t)
        self.steps.append(('xor', t, bit, None))

    def toffoli_into(self, x, y, t: int) -> None:
        """t ^= x & y with a Toffoli, for a qubit t made on this tape. Undone by a Toffoli."""
        with Held(self.em, x) as a, Held(self.em, y) as b:
            self.em.ccx(a, b, t)
        self.steps.append(('ccx', t, x, y))

    def undo(self) -> None:
        unplay(self.em, self.steps, {})
        self.steps = []


def rename(bit, now):
    """A bit with its qubits replaced by the ones that hold their values now."""
    return frozenset(now.get(q, q) for q in bit[0]), bit[1]


def play(em: Emitter, steps, now) -> None:
    """Makes the ANDs of a tape again, in new qubits. `now` maps the qubits the steps were
    first made in to the ones that hold those values now, and is updated."""
    for kind, t, x, y in steps:
        if kind == 'and':
            now[t] = em.alloc(1)[0]
            with Held(em, rename(x, now)) as a, Held(em, rename(y, now)) as b:
                em.ccx(a, b, now[t])
        else:
            assert kind == 'xor'
            xor_into(em, rename(x, now), now[t])


def unplay(em: Emitter, steps, now) -> None:
    """Takes the steps of a tape back in reverse order: an AND is measured in the X basis
    and its phase fixed by a CZ on its two inputs."""
    for kind, t, x, y in reversed(steps):
        q = now.get(t, t)
        if kind == 'xor':
            xor_into(em, rename(x, now), q)
        elif kind == 'ccx':
            with Held(em, rename(x, now)) as a, Held(em, rename(y, now)) as b:
                em.ccx(a, b, q)
        else:
            em.hmr(q)
            with Held(em, rename(x, now)) as a, Held(em, rename(y, now)) as b:
                em.cz_if(a, b, 'b0')
            em.release([q], reset=False)


# ---- sums --------------------------------------------------------------------------------

def carry_row(tape: Tape, x, y, z, cin: int = 0):
    """The carry row of a carry-save step: bit 0 is `cin`, bit k + 1 is
    Maj(x_k, y_k, z_k) = ((x ^ z) & (y ^ z)) ^ z."""
    row = [(frozenset(), cin)]
    for k in range(WORD - 1):
        row.append(tape.and_xor(xor(x[k], z[k]), xor(y[k], z[k]), z[k]))
    return row


def two_rows(em: Emitter, tape: Tape, terms, const: int = 0, cin: int = 0):
    """Reduces sum(terms) + const + cin to two rows by carry-save steps, earliest rows
    first. `cin` is 0 or 1 and goes into the free low bit of a carry row."""
    rows = []
    for term in terms:
        term = as_row(term)
        if any(q for q, _ in term):
            rows.append(term)
        else:
            const += sum(c << k for k, (_, c) in enumerate(term))
    const &= MASK
    if cin and (const or len(rows) < 3):
        const, cin = (const + cin) & MASK, 0
    if const:
        rows.insert(0, constant(const))
    while len(rows) > 2:
        rows.sort(key=lambda row: arrival(em, row))
        x, y, z = rows[:3]
        rows = [xor_rows(x, y, z), carry_row(tape, x, y, z, cin)] + rows[3:]
        cin = 0
    assert not cin, 'no carry row to take the carry-in'
    while len(rows) < 2:
        rows.append(constant(0))
    return rows


def carries(tape: Tape, x, y, kind: str, in_place: int = 0, keep: bool = False):
    """The carry into each bit of x + y and the propagate of each bit, as bits.

    The generate and propagate of every node of the prefix tree are ANDs on the tape. When
    y is a row of qubits made on this tape, x is written into them first, so that they hold
    the propagates while the tree stands and every node has single qubits for inputs.

    Up to `in_place` merges write into the qubit of the generate they update, with a Toffoli
    that a Toffoli undoes. With `keep`, every carry is built that way in a qubit that is not
    on the tape: the caller keeps those qubits.
    """
    em, n = tape.em, WORD - 1

    def scratch(bit) -> bool:
        return len(bit[0]) == 1 and not bit[1] and next(iter(bit[0])) in tape.made

    if keep:
        generate = []
        for i in range(n):
            g = em.alloc(1)[0]
            bit = Tape(em).and_(x[i], y[i]) if not x[i][0] or not y[i][0] or x[i][0] == y[i][0] else None
            if bit is not None:  # Plain from the inputs: no AND is needed.
                xor_into(em, bit, g)
            else:
                with Held(em, x[i]) as a, Held(em, y[i]) as b:
                    em.ccx(a, b, g)
            generate.append((frozenset([g]), 0))
    else:
        generate = [tape.and_(x[i], y[i]) for i in range(n)]
    if kind == 'ripple':
        carry = [ZERO, generate[0]]
        for i in range(1, n):
            carry.append(xor(tape.and_(xor(x[i], carry[i]), xor(y[i], carry[i])), carry[i]))
        return carry, [xor(x[i], y[i]) for i in range(WORD)]

    if all(scratch(y[i]) for i in range(1, n)):
        for i in range(1, n):
            tape.write(x[i], next(iter(y[i][0])))
        propagate = [xor(x[0], y[0])] + [y[i] for i in range(1, n)] + [xor(x[n], y[n])]
    else:
        propagate = [xor(x[i], y[i]) for i in range(WORD)]
    group = list(propagate[:n])  # The propagate of the group of bits each node stands for.
    left = [in_place]

    def merge(i: int, j: int, keep_propagate: bool) -> None:
        if keep:
            if group[i][0] and generate[j][0]:
                with Held(em, group[i]) as a, Held(em, generate[j]) as b:
                    em.ccx(a, b, next(iter(generate[i][0])))
        elif left[0] > 0 and scratch(generate[i]) and generate[j][0] and group[i][0]:
            left[0] -= 1
            tape.toffoli_into(group[i], generate[j], next(iter(generate[i][0])))
        else:
            generate[i] = xor(tape.and_(group[i], generate[j]), generate[i])
        if keep_propagate:
            group[i] = tape.and_(group[i], group[j])

    if kind == 'sklansky':
        # Bit i sits at index i + 1 of a 32-wide grid whose index 0 is empty, so no carry is
        # merged more than four times.
        for level in range(5):
            for index in range(1, WORD):
                if (index >> level) & 1:
                    below = ((index >> level) << level) - 1
                    if below >= 1:
                        start = (index >> (level + 1)) << (level + 1)
                        merge(index - 1, below - 1, start > 0 and level < 4)
    else:  # Brent-Kung: up the tree, then down.
        d = 1
        while d < n:
            for i in range(2 * d - 1, n, 2 * d):
                merge(i, i - d, i - 2 * d + 1 > 0)
            d *= 2
        d //= 2
        while d >= 1:
            for i in range(3 * d - 1, n, 2 * d):
                merge(i, i - d, False)
            d //= 2
    return [ZERO] + generate, propagate


def form(em: Emitter, terms, const: int = 0, cin: int = 0) -> list[int]:
    """A fresh register holding (sum(terms) + const + cin) mod 2^32.

    Bit k of the sum is its propagate XOR the carry into it. The carries are built in place
    in qubits of their own, and each of those qubits then takes the propagate of its bit and
    is the bit. Only bit 0, which has no carry, needs one more qubit.
    """
    tape = Tape(em)
    x, y = two_rows(em, tape, terms, const, cin)
    carry, propagate = carries(tape, x, y, 'brent-kung', keep=True)
    out = em.alloc(1) + [next(iter(carry[k][0])) for k in range(1, WORD)]
    for k in range(WORD):
        xor_into(em, propagate[k], out[k])
    tape.undo()
    return out


def clear(em: Emitter, reg: list[int], terms, const: int = 0, cin: int = 0, tree=('sklansky', 0)) -> None:
    """Clears and frees `reg`, which holds sum(terms) + const + cin.

    The register is measured in the X basis first, so its qubits are free at once. Then the
    sum is computed once more and the phase fixed on its bits: a Z on every qubit that a bit
    of the sum is the XOR of. A constant 1 in a bit is fixed on a qubit set to 1.
    """
    for k in range(WORD):
        em.hmr(reg[k], f'b{k + 1}')
    em.release(reg, reset=False)
    tape = Tape(em)
    x, y = two_rows(em, tape, terms, const, cin)
    carry, propagate = carries(tape, x, y, tree[0], in_place=tree[1])
    total = [xor(propagate[k], carry[k]) for k in range(WORD)]
    if any(c for _, c in total):
        one = em.alloc(1)[0]
        em.x(one)
        for k in range(WORD):
            if total[k][1]:
                em.z_if(one, f'b{k + 1}')
        em.x(one)
        em.release([one])
    for k in range(WORD):
        for q in sorted(total[k][0]):
            em.z_if(q, f'b{k + 1}')
    tape.undo()


def replace(em: Emitter, old: list[int], terms, const: int = 0, tree=('sklansky', 0)) -> list[int]:
    """A fresh register holding old + sum(terms) + const, with `old` cleared against it:
    old = ~(~new + sum(terms) + const)."""
    new = form(em, [old] + terms, const)
    for q in old:
        em.x(q)
    clear(em, old, [inv(new)] + terms, const, tree=tree)
    return new


# ---- SHA-256 -----------------------------------------------------------------------------

class SharedRows:
    """d + K + W + Sigma1(e) + Ch(e, f, g) as two rows, for the two sums of a round that
    use them.

    Three carry-save steps make the rows: carry rows k1, k2 and k3, with Ch going in last.
    Kept as they are, the rows need those three rows and Ch, 124 qubits. Here the XOR row
    is written into a register instead and only k3 stays: 63 qubits. The others are measured
    away, which is free, and made again when the rows are taken apart. A row can only be
    measured away or made while the rows it was computed from are there, and k1, the
    cheapest to make, is the one that is made again whenever that is needed, so that no more
    than three of the four are ever held at once.
    """

    def __init__(self, em: Emitter, d, w, k: int, e, f, g) -> None:
        self.em = em
        first = [as_row(w), d, constant(k)]
        self.lean = not any(not any(q for q, _ in row) for row in first[:2])
        sigma1 = sigma(e, BIG_SIGMA1)
        if not self.lean:  # A first round, where d is a constant: nothing to save.
            self.tape = Tape(em)
            ch = [self.tape.and_xor(e[i], xor(f[i], g[i]), g[i]) for i in range(WORD)]
            self.rows = two_rows(em, self.tape, [d, w, sigma1, ch], k)
            return
        self.now = now = {}

        def made(build):
            tape = Tape(em)
            row = build(tape)
            return tape.steps, row

        self.xor1 = xor_rows(*first)
        self.k1_steps, self.k1 = made(lambda tape: carry_row(tape, *first))
        self.k2_steps, self.k2 = made(lambda tape: carry_row(tape, self.xor1, self.k1, sigma1))
        self.xor2 = xor_rows(self.xor1, self.k1, sigma1)
        self.held = em.alloc(WORD)
        self.write(self.xor2)                           # held = xor2
        unplay(em, self.k1_steps, now)
        self.ch_steps, self.ch = made(
            lambda tape: [tape.and_xor(e[i], xor(f[i], g[i]), g[i]) for i in range(WORD)])
        self.k3_steps, k3 = made(lambda tape: carry_row(tape, register(self.held), self.k2, self.ch))
        self.write(xor_rows(self.k2, self.ch))          # held = xor2 ^ k2 ^ Ch, the XOR row
        unplay(em, self.ch_steps, now)
        play(em, self.k1_steps, now)                    # k2 is measured away against k1
        unplay(em, self.k2_steps, now)
        unplay(em, self.k1_steps, now)
        self.rows = [register(self.held), k3]

    def write(self, row) -> None:
        for i in range(WORD):
            xor_into(self.em, rename(row[i], self.now), self.held[i])

    def undo(self) -> None:
        em = self.em
        if not self.lean:
            self.tape.undo()
            return
        now = self.now
        play(em, self.k1_steps, now)
        play(em, self.k2_steps, now)
        unplay(em, self.k1_steps, now)
        play(em, self.ch_steps, now)
        self.write(xor_rows(self.k2, self.ch))          # held = xor2 again
        unplay(em, self.k3_steps, now)
        unplay(em, self.ch_steps, now)
        play(em, self.k1_steps, now)
        self.write(self.xor2)                           # held = 0
        em.release(self.held)
        unplay(em, self.k2_steps, now)
        unplay(em, self.k1_steps, now)


class Builder:
    def __init__(self, resets: bool = True) -> None:
        # The digest qubits start at zero and are used as scratch; the result goes wherever
        # the last step leaves it, and the digest register is declared there.
        self.em = Emitter(768, list(range(512, 768)), resets)
        self.w = [list(range(WORD * j, WORD * (j + 1))) for j in range(16)]

    def schedule_rows(self, tape: Tape, t: int):
        """W_t - W_(t-16) as two rows: sigma0(W_(t-15)) + W_(t-7) + sigma1(W_(t-2))."""
        return two_rows(self.em, tape, [sigma(self.w[(t - 15) % 16], SMALL_SIGMA0),
                                        register(self.w[(t - 7) % 16]),
                                        sigma(self.w[(t - 2) % 16], SMALL_SIGMA1)])

    def schedule(self, t: int) -> None:
        """Replaces the register of W_(t-16) by one holding W_t."""
        tape = Tape(self.em)
        rows = self.schedule_rows(tape, t)
        self.w[t % 16] = replace(self.em, self.w[t % 16], rows, tree=SCHEDULE_CLEAR)
        tape.undo()

    def unschedule(self, t: int) -> None:
        """Replaces the register of W_t by one holding W_(t-16) = ~(~W_t + the rows)."""
        em = self.em
        tape = Tape(em)
        rows = self.schedule_rows(tape, t)
        old = self.w[t % 16]
        new = form(em, [inv(old)] + rows)
        for q in new:
            em.x(q)
        clear(em, old, [new] + rows, tree=REWIND_CLEAR)
        self.w[t % 16] = new
        tape.undo()

    def round(self, t: int, state: list) -> list:
        """One round. State words are registers, or constant rows in the first rounds.

            e' = h + (d + K + W + Sigma1(e) + Ch(e, f, g))       h = e' - (the same rows)
            a' = -d + (e' + Sigma0(a) + Maj(a, b, c))            d = (the same rows) - a'

        The sum in brackets is reduced to two rows once and used for both.
        """
        em = self.em
        a, b, c, d, e, f, g, h = [as_row(word) for word in state]

        shared = SharedRows(em, d, self.w[t % 16], K[t], e, f, g)
        e_new = form(em, [h] + shared.rows)
        if isinstance(state[7][0], int):  # h = ~(~e' + rows)
            for q in state[7]:
                em.x(q)
            clear(em, state[7], [inv(e_new)] + shared.rows, tree=ROUND_CLEAR)
        shared.undo()

        tape = Tape(em)
        maj = [tape.and_xor(xor(a[k], c[k]), xor(b[k], c[k]), c[k]) for k in range(WORD)]
        rows = two_rows(em, tape, [e_new, sigma(a, BIG_SIGMA0), maj])
        a_new = form(em, [inv(d)] + rows, cin=1)
        if isinstance(state[3][0], int):  # d = rows + ~a' + 1
            clear(em, state[3], [inv(a_new)] + rows, cin=1, tree=ROUND_CLEAR)
        tape.undo()
        return [a_new, state[0], state[1], state[2], e_new, state[4], state[5], state[6]]

    def build(self) -> km.Circuit:
        em = self.em
        state = [constant(v) for v in IV]
        for t in range(64):
            if t >= 16:
                self.schedule(t)
            state = self.round(t, state)
        for j in range(8):  # Feed-forward.
            state[j] = replace(em, state[j], [], IV[j], tree=FINAL_CLEAR)
        for t in reversed(range(16, 64)):  # Restore the block.
            self.unschedule(t)
        self.bring_home(state)

        header = [f'APPEND_TO_REGISTER q{q} r0' for q in range(512)] + ['REGISTER r0 "block"']
        header += [f'APPEND_TO_REGISTER q{q} r1' for reg in state for q in reg] + ['REGISTER r1 "digest"']
        return km.Circuit('\n'.join(header + em.ops))

    def bring_home(self, state: list) -> None:
        """Swaps the block words back to qubits 0 .. 511; every step left them elsewhere."""
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
