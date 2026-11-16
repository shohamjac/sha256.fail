"""Builds a SHA-256 compression circuit for `sha256-compress-v1` that sits on the front of
the reaction-depth track between the fewest-qubit circuit and `../lean-lookahead-rounds`.

This one: rounds in place, five additions a round, and an adder in parts of four bits
with every carry between parts kept. 782 qubits.

It reuses the generator of `../lean-lookahead-rounds` (rows that are never stored, the
prefix network, the in-place adder with Draper's carry erasure) and changes two things, set
by the constants below:

- The adder works on the word in parts of PART bits. A part needs one carry qubit per bit
  and a small tree for its propagates; the carry into each part is kept in a qubit of its
  own. With PEBBLE those carries are not all kept: the carry into a part is made from the
  carry into an earlier part whenever it is needed and unmade the same way, by the rule of
  a reversible pebble game on a line, so that a 32-bit addition holds five of them at most.
- With FRESH off, the rounds work in place on the eight state registers, as the baseline
  does, so no register is formed afresh: T1 goes into h and d, T2 into h. ORDER says how
  many additions that takes. 'plain' adds the seven terms one at a time. 'two' reduces
  K + W + Sigma1 + Ch to two rows that are never stored and adds those. 'direct' adds T1
  straight into d as two such rows as well, with K held in the register of W for the round.

Usage, from this directory:

    uv run --project ../../sha256_verifier python build.py
"""

from __future__ import annotations

import importlib.util
import pathlib

import kickmix as km

_spec = importlib.util.spec_from_file_location(
    'lean_build', pathlib.Path(__file__).parent.parent / 'lean-lookahead-rounds' / 'build.py')
lean = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lean)

WORD, K, IV = lean.WORD, lean.K, lean.IV
Poly = lean.Poly

FRESH = False    # New state words in fresh registers, as in lean-lookahead-rounds.
ORDER = 'two'  # For rounds in place: 'plain', 'two' or 'direct'.
PART = 4        # Bits per part of the adder.
PEBBLE = False   # Keep only a few of the carries between parts.

# The parts are counted down from the top, so the lowest one may be shorter.
BOUNDS = sorted(set([0] + list(range(WORD - 1, 0, -PART))))


# ---- adder -------------------------------------------------------------------------------

def part_levels(lo: int, hi: int):
    """Sklansky steps for the carries of bits lo .. hi - 1 alone, the first position of the
    grid left empty: (i, j) means G[i] ^= P(j+1 .. i) & G[j]."""
    size, levels, level = hi - lo, [], 0
    while (1 << level) <= size:
        steps = []
        for index in range(1, size + 1):
            if (index >> level) & 1:
                below = ((index >> level) << level) - 1
                if below >= 1:
                    steps.append((lo + index - 1, lo + below - 1))
        levels.append(steps)
        level += 1
    return levels


def add(em, a, b: list[int], first=None) -> None:
    """`b += a` modulo 2^32 in place, part by part. `a` is a row and is left unchanged.
    With `first`, b starts at zero and ends as first + a.

    In each part the carries come from a prefix network and the carry into the part, are
    XORed into b, and are erased with Draper's identity carries(a, b) == carries(a, ~s).
    The carry into a part is the carry out of the part below. It can be computed from the
    carry into that part at any time, from (a, b) before the part is added and from (a, ~s)
    after, and uncomputed the same way.
    """
    n, parts = len(b), len(BOUNDS) - 1
    b_row = Poly.reg(b)
    into = {}     # Part -> the qubit holding the carry into its lowest bit.
    added = set()  # Parts whose bits already hold the sum.

    def constant(i: int) -> bool:
        return isinstance(a, Poly) and not a.bits[i]

    def take(lo: int, hi: int, g) -> None:
        """g[i] ^= a_i & b_i, then b_i ^= a_i, with one build of each bit of a."""
        for i in range(lo, hi):
            if constant(i):
                lean.and_rows_into(em, [(a, i)], [(b_row, i)], g[i])
                lean.row_xor_into(em, a, i, b[i])
            else:
                with lean.HoldBits(em, [(a, i)]) as q:
                    em.ccx(q, b[i], g[i])
                    em.cx(q, b[i])

    def give(lo: int, hi: int, g) -> None:
        """The inverse of `take`."""
        for i in range(lo, hi):
            if constant(i):
                lean.row_xor_into(em, a, i, b[i])
                lean.and_rows_into(em, [(a, i)], [(b_row, i)], g[i])
            else:
                with lean.HoldBits(em, [(a, i)]) as q:
                    em.cx(q, b[i])
                    em.ccx(q, b[i], g[i])

    def xor_a(lo: int, hi: int) -> None:
        for i in range(lo, hi):
            lean.row_xor_into(em, a, i, b[i])

    def flip(lo: int, hi: int) -> None:
        for i in range(lo, hi):
            em.x(b[i])

    def carries(j: int, g, inverse: bool) -> None:
        """The carries out of the bits of part j, from generates and propagates in place."""
        lo, hi = BOUNDS[j], BOUNDS[j + 1]
        if inverse and j:
            lean._merge_carry_in(em, g, b, into[j], lo, hi, inverse=True)
        lean._prefix(em, g, b, part_levels(lo, hi), inverse)
        if not inverse and j:
            lean._merge_carry_in(em, g, b, into[j], lo, hi, inverse=False)

    def toggle_next(j: int) -> None:
        """Makes the carry into part j + 1, or unmakes it, given the carry into part j."""
        lo, hi = BOUNDS[j], BOUNDS[j + 1]
        g = dict(zip(range(lo, hi), em.alloc(hi - lo)))
        if j in added:
            flip(lo, hi)
        take(lo, hi, g)
        carries(j, g, inverse=False)
        if j + 1 not in into:
            into[j + 1] = em.alloc(1)[0]
            em.cx(g[hi - 1], into[j + 1])
        else:
            em.cx(g[hi - 1], into[j + 1])
            em.release([into.pop(j + 1)])
        carries(j, g, inverse=True)
        give(lo, hi, g)
        if j in added:
            flip(lo, hi)
        em.release(list(g.values()))

    def add_part(j: int, keep_next: bool) -> None:
        """Adds a into the bits of part j, given the carry into it."""
        lo, hi = BOUNDS[j], BOUNDS[j + 1]
        end = n if j == parts - 1 else hi  # The top bit takes a carry and gives none.
        g = dict(zip(range(lo, hi), em.alloc(hi - lo)))
        take(lo, hi, g)  # b = a ^ b: the propagates.
        xor_a(hi, end)
        carries(j, g, inverse=False)
        if j:
            em.cx(into[j], b[lo])
        if keep_next:
            into[j + 1] = em.alloc(1)[0]
            em.cx(g[hi - 1], into[j + 1])
        for i in range(lo, hi):
            if i + 1 < end:
                em.cx(g[i], b[i + 1])  # b = s.
        flip(lo, hi)
        xor_a(lo, hi)  # b = a ^ ~s.
        carries(j, g, inverse=True)  # g[i] = a_i & ~s_i.
        give(lo, hi, g)
        flip(lo, hi)
        em.release(list(g.values()))
        added.add(j)

    def toggle(lo: int, hi: int) -> None:
        """Makes or unmakes the carry into part hi given the carry into part lo, leaving the
        carries in between as they were."""
        if hi - lo == 1:
            toggle_next(lo)
            return
        mid = (lo + hi) // 2
        toggle(lo, mid)
        toggle(mid, hi)
        toggle(lo, mid)

    def add_parts(lo: int, hi: int) -> None:
        """Adds parts lo .. hi - 1, given the carry into part lo."""
        if hi - lo == 1:
            add_part(lo, keep_next=False)
            return
        mid = (lo + hi) // 2
        add_parts(lo, mid)
        toggle(lo, mid)
        add_parts(mid, hi)
        toggle(lo, mid)

    if first is not None:
        for i in range(n):
            lean.row_xor_into(em, first, i, b[i])
    if PEBBLE:
        add_parts(0, parts)
    else:
        for j in range(parts):
            add_part(j, keep_next=j < parts - 1)
        for j in reversed(range(1, parts)):  # Erase the kept carries, the last one first.
            toggle_next(j - 1)
    assert not into


def subtract(em, a, b: list[int]) -> None:
    """`b -= a`: b - a = ~(~b + a)."""
    for q in b:
        em.x(q)
    add(em, a, b)
    for q in b:
        em.x(q)


def add_sum(em, terms, target: list[int], const: int = 0) -> None:
    """target += sum(terms) + const, as two additions of rows that are never stored."""
    first, operand = lean.two_rows(em, terms, const)
    add(em, operand, target)
    add(em, first, target)


# ---- SHA-256 with rounds in place --------------------------------------------------------

class InPlaceBuilder:
    def __init__(self, resets: bool = True) -> None:
        self.em = lean.Emitter(768, [], resets)
        self.w = [list(range(WORD * j, WORD * (j + 1))) for j in range(16)]

    def schedule_terms(self, t: int):
        return (lean.sigma(self.w[(t - 15) % 16], lean.SMALL_SIGMA0), Poly.reg(self.w[(t - 7) % 16]),
                lean.sigma(self.w[(t - 2) % 16], lean.SMALL_SIGMA1))

    def round(self, t: int, state: list) -> list:
        """With T1 = h + Sigma1(e) + Ch(e,f,g) + K + W and T2 = Sigma0(a) + Maj(a,b,c), the
        new state is (T1 + T2, a, b, c, d + T1, e, f, g): h and d are updated in place."""
        em = self.em
        a, b, c, d, e, f, g, h = state
        w = Poly.reg(self.w[t % 16])
        s1, ch = lean.sigma(e, lean.BIG_SIGMA1), lean.ch(e, f, g)
        s0, maj = lean.sigma(a, lean.BIG_SIGMA0), lean.maj(a, b, c)
        if ORDER == 'plain':
            for row in (s1, ch, Poly.constant(K[t]), w):
                add(em, row, h)
            add(em, Poly.reg(h), d)
        elif ORDER == 'two':
            add_sum(em, [w, s1, ch], h, K[t])
            add(em, Poly.reg(h), d)
        else:
            # K sits in the register of W for the round: one row less in each sum.
            add(em, Poly.constant(K[t]), self.w[t % 16])
            add_sum(em, [w, Poly.reg(h), s1, ch], d)
            add_sum(em, [w, s1, ch], h)
            subtract(em, Poly.constant(K[t]), self.w[t % 16])
        add(em, s0, h)
        add(em, maj, h)
        return [h, a, b, c, d, e, f, g]

    def build(self) -> km.Circuit:
        em = self.em
        state = [list(range(512 + WORD * j, 512 + WORD * (j + 1))) for j in range(8)]
        for reg, value in zip(state, IV):  # digest starts at zero: write the IV with X gates.
            for k in range(WORD):
                if (value >> k) & 1:
                    em.x(reg[k])
        for t in range(64):
            if t >= 16:
                for term in self.schedule_terms(t):
                    add(em, term, self.w[t % 16])
            state = self.round(t, state)
        for j in range(8):  # Feed-forward.
            add(em, Poly.constant(IV[j]), state[j])
        for t in reversed(range(16, 64)):  # Restore the block.
            s0, middle, s1 = self.schedule_terms(t)
            for term in (s1, middle, s0):
                subtract(em, term, self.w[t % 16])

        header = [f'APPEND_TO_REGISTER q{q} r0' for q in range(512)] + ['REGISTER r0 "block"']
        header += [f'APPEND_TO_REGISTER q{q} r1' for reg in state for q in reg] + ['REGISTER r1 "digest"']
        return km.Circuit('\n'.join(header + em.ops))


def builder(resets: bool = True):
    if FRESH:
        lean.add = add  # The lean rounds, with this adder in place of theirs.
        return lean.Builder(resets)
    return InPlaceBuilder(resets)


def main() -> None:
    # The same circuit without resets: a reset would hide scratch that was not cleared.
    lean.baseline.check(builder(resets=False).build())
    circuit = builder().build()
    lean.baseline.check(circuit)
    path = pathlib.Path(__file__).with_name('circuit.kmb')
    circuit.to_file(path, format='kmb')
    stats = circuit.operation_statistics()
    print(f'Wrote {path.name}: {circuit.num_qubits} qubits, reaction depth {circuit.reaction_depth()}, '
          f'{stats.num_toffoli_like} Toffolis, {len(circuit)} operations, {path.stat().st_size} bytes. '
          f'Matches hashlib on 1024 messages.')


if __name__ == '__main__':
    main()
