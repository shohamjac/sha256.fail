"""A reconstruction of the garbage-free SHA-256 circuit of the qSHA256 project.

Source: https://github.com/icedmoca/qSHA256 at commit 741fe86 (version 2.3.0), default
architecture with uncomputation: `cdkm/load/rolling/serial/uncomp`.

This file is a re-implementation written from reading that project's source. It does not
import or run any of it. The construction, in that project's terms:

- Registers: chaining state H (256 qubits), message M (512), working variables a..h (256),
  digest D (256), and a pool of 33 ancillas: one 32-qubit temporary and one adder carry.
- H is copied into the working variables with CNOTs.
- A round updates two registers in place: h += Sigma1(e) + Ch(e,f,g) + K + W, d += h,
  h += Sigma0(a) + Maj(a,b,c); the registers are then relabelled. Each Sigma, Ch and Maj is
  written into the temporary, added, and erased by repeating the same gates.
- The message schedule rolls in place over M: W_(t-16) becomes W_t.
- Every addition is the ripple-carry adder of Cuccaro, Draper, Kutin and Moulton
  (arXiv:quant-ph/0410184). Round constants are written into the temporary, added, erased.
- The result is copied from the working variables into D and H is added to it. Then the
  copy, schedule and rounds are replayed backwards, which clears the working variables and
  restores M.
- Gates: X, CNOT and Toffoli only. No measurement.

Adaptation to the problem `sha256-compress-v1`: M is the `block` register and D is the
`digest` register. H is scratch here, so it is set to the initial hash value with X gates
at the start and cleared with the same X gates at the end; qSHA256 leaves it holding its
input. Nothing else differs.

Counts. qSHA256's adder changed in version 2.3.0 from 2n to 2(n-1) Toffolis per addition,
but its published tables predate the change. `--published-adder` builds with the older
adder and reproduces those tables exactly: 1,313 qubits, 92,672 Toffolis, 399,044 gates.
The circuit submitted here uses the current adder: 1,313 qubits, 90,288 Toffolis.

Usage, from this directory:

    uv run --project ../../sha256_verifier python build.py
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import kickmix as km

# Only the checking helpers are shared with the baseline; the circuit is built here.
_spec = importlib.util.spec_from_file_location(
    'baseline_build', pathlib.Path(__file__).parent.parent / 'example' / 'build.py')
baseline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(baseline)

WORD, K, IV = baseline.WORD, baseline.K, baseline.IV

ROTR, SHR = 'rotr', 'shr'
BIG_SIGMA0 = ((ROTR, 2), (ROTR, 13), (ROTR, 22))
BIG_SIGMA1 = ((ROTR, 6), (ROTR, 11), (ROTR, 25))
SMALL_SIGMA0 = ((ROTR, 7), (ROTR, 18), (SHR, 3))
SMALL_SIGMA1 = ((ROTR, 17), (ROTR, 19), (SHR, 10))

Gate = tuple  # ('X', q), ('CX', control, target) or ('CCX', control, control, target).

# X gates that load the initial hash value into H and clear it again (the adaptation).
IV_LOAD_GATES = 2 * sum(bin(value).count('1') for value in IV)


class QSha256Reconstruction:
    """Builds the circuit as a list of gates over numbered qubits."""

    def __init__(self, *, published_adder: bool = False) -> None:
        self.published_adder = published_adder
        self.gates: list[Gate] = []
        words = lambda start, count: [list(range(start + WORD * j, start + WORD * (j + 1))) for j in range(count)]
        self.m = words(0, 16)  # `block`
        self.d = words(512, 8)  # `digest`
        self.h = words(768, 8)  # Chaining state; scratch in this problem.
        self.wv = words(1024, 8)  # Working variables a..h.
        self.tmp = list(range(1280, 1312))
        self.carry = 1312
        self.num_qubits = 1313

    # Primitives.

    def xor_const(self, value: int, target: list[int]) -> None:
        self.gates += [('X', target[i]) for i in range(WORD) if (value >> i) & 1]

    def xor_word(self, source: list[int], target: list[int]) -> None:
        self.gates += [('CX', s, t) for s, t in zip(source, target)]

    def xor_terms(self, source: list[int], terms, target: list[int]) -> None:
        """`target ^= sigma(source)`; applying it twice restores `target`."""
        for kind, amount in terms:
            if kind == ROTR:  # Bit i of a right rotation is bit i + amount of the source.
                self.gates += [('CX', source[(i + amount) % WORD], target[i]) for i in range(WORD)]
            else:  # A right shift drops the bits that would wrap.
                self.gates += [('CX', source[i + amount], target[i]) for i in range(WORD - amount)]

    def add(self, a: list[int], target: list[int]) -> None:
        """`target += a (mod 2^32)`: the Cuccaro adder, the carry rippling through `a`."""
        carry_in = [self.carry, *a[:WORD - 1]]
        maj = lambda c, y, x: [('CX', x, y), ('CX', x, c), ('CCX', c, y, x)]
        uma = lambda c, y, x: [('CCX', c, y, x), ('CX', x, c), ('CX', c, y)]
        top = WORD if self.published_adder else WORD - 1
        for i in range(top):
            self.gates += maj(carry_in[i], target[i], a[i])
        if not self.published_adder:
            # The top MAJ and UMA cancel down to two CNOTs, since the carry out is discarded.
            self.gates += [('CX', a[WORD - 1], target[WORD - 1]), ('CX', carry_in[WORD - 1], target[WORD - 1])]
        for i in reversed(range(top)):
            self.gates += uma(carry_in[i], target[i], a[i])

    def add_const(self, value: int, target: list[int]) -> None:
        self.xor_const(value, self.tmp)
        self.add(self.tmp, target)
        self.xor_const(value, self.tmp)

    def add_sigma(self, source: list[int], terms, target: list[int]) -> None:
        self.xor_terms(source, terms, self.tmp)
        self.add(self.tmp, target)
        self.xor_terms(source, terms, self.tmp)

    def ch_into_tmp(self, x: list[int], y: list[int], z: list[int], *, undo: bool = False) -> None:
        """`tmp ^= Ch(x, y, z)`, one Toffoli per bit. An involution, so `undo` is the same gates."""
        for xi, yi, zi, ti in zip(x, y, z, self.tmp):
            self.gates += [('CX', zi, yi), ('CCX', xi, yi, ti), ('CX', zi, yi), ('CX', zi, ti)]

    def maj_into_tmp(self, x: list[int], y: list[int], z: list[int], *, undo: bool = False) -> None:
        """`tmp ^= Maj(x, y, z)`, one Toffoli per bit. An involution, so `undo` is the same gates."""
        for xi, yi, zi, ti in zip(x, y, z, self.tmp):
            self.gates += [('CX', xi, yi), ('CX', xi, zi), ('CCX', yi, zi, ti),
                           ('CX', xi, zi), ('CX', xi, yi), ('CX', xi, ti)]

    def inverse(self, gate: Gate) -> Gate:
        """The gate that undoes `gate`. X, CNOT and Toffoli each undo themselves."""
        return gate

    def emit(self, gate: Gate) -> list[str]:
        """The Kickmix instructions for one gate."""
        name, *qubits = gate
        return [f'{name} ' + ' '.join(f'q{q}' for q in qubits)]

    # SHA-256.

    def round(self, t: int, state: list[list[int]]) -> list[list[int]]:
        a, b, c, d, e, f, g, h = state
        self.add_sigma(e, BIG_SIGMA1, h)
        self.ch_into_tmp(e, f, g)
        self.add(self.tmp, h)
        self.ch_into_tmp(e, f, g, undo=True)
        self.add_const(K[t], h)
        self.add(self.m[t % 16], h)  # h holds T1.
        self.add(h, d)
        self.add_sigma(a, BIG_SIGMA0, h)
        self.maj_into_tmp(a, b, c)
        self.add(self.tmp, h)
        self.maj_into_tmp(a, b, c, undo=True)  # h holds T1 + T2.
        return [h, a, b, c, d, e, f, g]

    def schedule(self, t: int) -> None:
        """Turns W_(t-16) into W_t in place."""
        target = self.m[t % 16]
        self.add_sigma(self.m[(t - 2) % 16], SMALL_SIGMA1, target)
        self.add(self.m[(t - 7) % 16], target)
        self.add_sigma(self.m[(t - 15) % 16], SMALL_SIGMA0, target)

    def build_gates(self) -> list[Gate]:
        for word, value in zip(self.h, IV):  # Adaptation: H is scratch, so load the IV.
            self.xor_const(value, word)
        load = list(self.gates)

        forward_start = len(self.gates)
        for source, target in zip(self.h, self.wv):
            self.xor_word(source, target)
        state = list(self.wv)
        for t in range(64):
            if t >= 16:
                self.schedule(t)
            state = self.round(t, state)
        forward_end = len(self.gates)

        for i in range(8):  # Digest = final state + H, formed in the digest register.
            self.xor_word(state[i], self.d[i])
            self.add(self.h[i], self.d[i])

        # The uncomputation is the forward span replayed backwards, gate by inverse gate.
        self.gates += [self.inverse(gate) for gate in reversed(self.gates[forward_start:forward_end])]
        self.gates += load  # Adaptation: clear H.
        return self.gates

    def build(self) -> km.Circuit:
        gates = self.build_gates()
        lines = [f'APPEND_TO_REGISTER q{q} r0' for q in range(512)] + ['REGISTER r0 "block"']
        lines += [f'APPEND_TO_REGISTER q{q} r1' for q in range(512, 768)] + ['REGISTER r1 "digest"']
        lines += [line for gate in gates for line in self.emit(gate)]
        return km.Circuit('\n'.join(lines) + '\n')


def published_counts() -> dict[str, int]:
    """Counts with the pre-2.3.0 adder, leaving out the X gates that load and clear H.

    These are the quantities in qSHA256's benchmarks/results/latest.md, row
    `sha256 compression | 64 | cdkm/load/rolling/serial/uncomp`.
    """
    builder = QSha256Reconstruction(published_adder=True)
    gates = builder.build_gates()
    iv_gates = IV_LOAD_GATES
    return {
        'qubits': builder.num_qubits,
        'toffoli': sum(gate[0] == 'CCX' for gate in gates),
        'gates': len(gates) - iv_gates,
    }


PUBLISHED = {'qubits': 1313, 'toffoli': 92672, 'gates': 399044}

if __name__ == '__main__':
    counts = published_counts()
    assert counts == PUBLISHED, f'reconstruction {counts} differs from the published table {PUBLISHED}'
    print(f'With the published adder: {counts}; matches the published table.')
    if '--published-adder' not in sys.argv:
        baseline.main(QSha256Reconstruction, __file__)
