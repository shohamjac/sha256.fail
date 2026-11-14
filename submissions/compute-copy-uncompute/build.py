"""A variant of the baseline built the textbook way: compute, copy, uncompute.

The baseline computes the hash state directly in the `digest` register, which the problem
lets it do because `digest` starts at zero. This variant does not rely on that: it computes
the state in 256 scratch qubits, copies the result into `digest` with CNOTs, and runs the
whole computation backwards to clean up. It costs 256 more qubits and nearly twice the
Toffolis, and is here as a point of comparison.

Everything else is the baseline; see ../example/build.py.

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


class ComputeCopyUncomputeBuilder(baseline.Sha256Builder):

    def unround(self, t: int, state: list[km.array]) -> list[km.array]:
        """The inverse of `round`: takes the registers holding a..h after round t."""
        h, a, b, c, d, e, f, g = state  # `round` returned [h, a, b, c, d, e, f, g].
        self.add_maj(a, b, c, h, subtract=True)
        self.add_linear(a, baseline.BIG_SIGMA0, h, subtract=True)  # h holds T1 again.
        self.add(h, d, subtract=True)
        self.add(self.w[t % 16], h, subtract=True)
        self.add(K[t], h, subtract=True)
        self.add_ch(e, f, g, h, subtract=True)
        self.add_linear(e, baseline.BIG_SIGMA1, h, subtract=True)
        return [a, b, c, d, e, f, g, h]

    def build(self) -> km.Circuit:
        scratch = self.b.alloc_qubits(8 * WORD)
        words = [scratch[WORD * j:WORD * (j + 1)] for j in range(8)]
        iv_bits = [word[k] for word, value in zip(words, IV) for k in range(WORD) if (value >> k) & 1]

        # Compute.
        self.b.x(iv_bits)
        state = list(words)
        for t in range(64):
            if t >= 16:
                self.schedule(t)
            state = self.round(t, state)
        for word, value in zip(words, IV):
            self.add(value, word)

        # Copy.
        for word, out in zip(words, self.h):
            self.b.cx(word, out)

        # Uncompute.
        for word, value in zip(words, IV):
            self.add(value, word, subtract=True)
        for t in reversed(range(64)):
            state = self.unround(t, state)
            if t >= 16:
                self.schedule(t, undo=True)
        assert all(now is start for now, start in zip(state, words)), 'state registers did not line up'
        self.b.x(iv_bits)

        self.b.free(scratch)
        self.b.free(self.tmp)
        return self.b.finish_circuit()


if __name__ == '__main__':
    baseline.main(ComputeCopyUncomputeBuilder, __file__)
