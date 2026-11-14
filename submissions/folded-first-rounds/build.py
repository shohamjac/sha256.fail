"""The baseline with its first four rounds simplified by constant folding.

SHA-256 starts from a fixed initial hash value, so for the first few rounds some of the
state is a known constant, and work the baseline does on it can be done at build time:

- Round 0. All of a..h are constants, so T1 = c1 + W_0 and T2 = c2 for constants c1, c2.
  The two registers the round changes are loaded with their constant parts and W_0 is
  added to each: two additions instead of seven additions and two rows of ANDs.
- Round 1. f, g and b, c are still constants, so Ch(e, f, g) and Maj(a, b, c) are, bit by
  bit, a constant, e (or a), or its complement: CNOTs and X gates, no ANDs.
- Rounds 1 to 3. The register that serves as h is still a constant, so the round constant
  K_t is added to it at build time instead of by an adder.
- Round 2. g is a constant, so Ch needs no register for it.

Everything from round 4 on, and the message schedule, is the baseline unchanged.
This saves 372 Toffolis and no qubits.

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


def rotr(x: int, n: int) -> int:
    return ((x >> n) | (x << (WORD - n))) & MASK


class FoldedBuilder(baseline.Sha256Builder):

    def bits(self, register: km.array, value: int) -> list:
        """The qubits of `register` at the set bits of `value`."""
        return [register[k] for k in range(WORD) if (value >> k) & 1]

    def xor_const(self, register: km.array, value: int) -> None:
        if value:
            self.b.x(self.bits(register, value))

    def xor_select(self, source: km.array, when_source: int, target: km.array) -> None:
        """`target ^= source` on the bits set in `when_source`."""
        if when_source:
            self.b.cx(km.array(self.bits(source, when_source)), km.array(self.bits(target, when_source)))

    def add_ch_two_constants(self, e: km.array, f: int, g: int, target: km.array) -> None:
        """`target += Ch(e, f, g)` for constants f and g. Per bit Ch is g where f = g, e where
        (f, g) = (1, 0), and not-e where (f, g) = (0, 1)."""
        def toggle() -> None:
            self.xor_select(e, f ^ g, self.tmp)
            self.xor_const(self.tmp, g)  # Bits with f = g = 1, and the complement where (f, g) = (0, 1).
        toggle()
        self.add(self.tmp, target)
        toggle()

    def add_maj_two_constants(self, a: km.array, b: int, c: int, target: km.array) -> None:
        """`target += Maj(a, b, c)` for constants b and c. Per bit Maj is b where b = c, else a."""
        def toggle() -> None:
            self.xor_select(a, b ^ c, self.tmp)
            self.xor_const(self.tmp, b & c)
        toggle()
        self.add(self.tmp, target)
        toggle()

    def add_ch_constant_g(self, e: km.array, f: km.array, g: int, target: km.array) -> None:
        """`target += Ch(e, f, g)` for a constant g, as g ^ (e & (f ^ g))."""
        self.xor_const(f, g)
        self.b.init_and(e, f, self.tmp)
        self.xor_const(self.tmp, g)
        self.add(self.tmp, target)
        self.xor_const(self.tmp, g)
        self.b.del_and(e, f, self.tmp)
        self.xor_const(f, g)

    def build(self) -> km.Circuit:
        A, B, C, D, E, F, G, H = IV
        sigma1 = rotr(E, 6) ^ rotr(E, 11) ^ rotr(E, 25)
        sigma0 = rotr(A, 2) ^ rotr(A, 13) ^ rotr(A, 22)
        t1 = (H + sigma1 + ((E & F) ^ (~E & G)) + K[0]) & MASK  # T1 of round 0 is t1 + W_0.
        t2 = (sigma0 + ((A & B) ^ (A & C) ^ (B & C))) & MASK

        # Initial values of the eight registers. Each constant that a later round would add
        # to a register while it is still a constant is included here instead.
        initial = [
            A,
            B,
            C,
            (D + t1) & MASK,  # Becomes e after round 0, once W_0 is added.
            (E + K[3]) & MASK,  # Serves as h in round 3.
            (F + K[2]) & MASK,  # Serves as h in round 2.
            (G + K[1]) & MASK,  # Serves as h in round 1.
            (t1 + t2) & MASK,  # Becomes a after round 0, once W_0 is added.
        ]
        for register, value in zip(self.h, initial):
            self.xor_const(register, value)
        r = self.h

        # Round 0: new e = D + T1 and new a = T1 + T2, each a constant plus W_0.
        self.add(self.w[0], r[3])
        self.add(self.w[0], r[7])
        state = [r[7], r[0], r[1], r[2], r[3], r[4], r[5], r[6]]

        # Round 1: f = E, g = F, b = A, c = B are constants; h already holds G + K_1.
        a, b, c, d, e, f, g, h = state
        self.add_linear(e, baseline.BIG_SIGMA1, h)
        self.add_ch_two_constants(e, E, F, h)
        self.add(self.w[1], h)
        self.add(h, d)
        self.add_linear(a, baseline.BIG_SIGMA0, h)
        self.add_maj_two_constants(a, A, B, h)
        state = [h, a, b, c, d, e, f, g]

        # Round 2: g = E is a constant; h already holds F + K_2.
        a, b, c, d, e, f, g, h = state
        self.add_linear(e, baseline.BIG_SIGMA1, h)
        self.add_ch_constant_g(e, f, E, h)
        self.add(self.w[2], h)
        self.add(h, d)
        self.add_linear(a, baseline.BIG_SIGMA0, h)
        self.add_maj(a, b, c, h)
        state = [h, a, b, c, d, e, f, g]

        # Round 3: a full round, except that h already holds E + K_3.
        a, b, c, d, e, f, g, h = state
        self.add_linear(e, baseline.BIG_SIGMA1, h)
        self.add_ch(e, f, g, h)
        self.add(self.w[3], h)
        self.add(h, d)
        self.add_linear(a, baseline.BIG_SIGMA0, h)
        self.add_maj(a, b, c, h)
        state = [h, a, b, c, d, e, f, g]

        for t in range(4, 64):
            if t >= 16:
                self.schedule(t)
            state = self.round(t, state)
        assert all(now is start for now, start in zip(state, self.h)), 'state registers did not line up'

        for word, value in zip(self.h, IV):
            self.add(value, word)
        for t in reversed(range(16, 64)):
            self.schedule(t, undo=True)

        self.b.free(self.tmp)
        return self.b.finish_circuit()


if __name__ == '__main__':
    baseline.main(FoldedBuilder, __file__)
