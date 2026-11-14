"""A reconstruction of the measurement-based garbage-free SHA-256 circuit of qSHA256.

Source: https://github.com/icedmoca/qSHA256 at commit 741fe86 (version 2.3.0),
configuration `gidney/load/rolling/serial/uncomp`.

This is qSHA256's lowest-cost configuration. It has the same architecture as the
Toffoli-only one rebuilt in ../literature-qsha256, with every Toffoli replaced by a
"temporary AND" (Gidney, arXiv:1709.06648): the AND is computed into a clean ancilla by a
Toffoli, and later removed by measuring that ancilla in the X basis and applying a
classically controlled CZ, which costs no Toffoli.

- Additions are Gidney's ripple-carry adder: 31 carries held in ancillas, one AND each.
- Ch and Maj are computed into a row of 32 AND ancillas, copied into the temporary, added,
  and removed by measurement.
- The uncomputation replays the forward computation backwards. The inverse of computing an
  AND is the measurement-based removal, and the inverse of a removal is computing it again.
- Ancillas: the 32-qubit temporary, 32 for Ch/Maj ANDs and 31 carries, 95 in all.

Like ../literature-qsha256/build.py, which it extends, this is a re-implementation written
from reading that project's source; it does not import or run any of it. The one adaptation
is the same: the chaining state is scratch here, loaded and cleared with X gates.

Counts. qSHA256's benchmark table lists this configuration at 1,375 qubits, 514,364 gates
and a T-count of 180,576, which at its 4 T per AND is 45,144 ANDs. This reconstruction has
exactly those counts, asserted below. A computed AND is one Toffoli in this benchmark's
metric, so the circuit costs 45,144 Toffolis.

Usage, from this directory:

    uv run --project ../../sha256_verifier python build.py
"""

from __future__ import annotations

import importlib.util
import pathlib


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_here = pathlib.Path(__file__).parent
unitary = _load('qsha256_unitary_build', _here.parent / 'literature-qsha256' / 'build.py')
baseline = unitary.baseline

WORD = unitary.WORD


class QSha256MeasuredReconstruction(unitary.QSha256Reconstruction):
    """The `gidney` configuration. Two gates join X and CX:

    ('AND', x, y, t): t, known to be zero, becomes x AND y. One Toffoli.
    ('UNAND', x, y, t): t, known to hold x AND y, is measured away. No Toffoli.
    """

    def __init__(self) -> None:
        super().__init__()
        self.and_row = list(range(1312, 1344))  # ANDs of Ch and Maj.
        self.carries = list(range(1344, 1375))  # Adder carries.
        self.num_qubits = 1375

    def add(self, a: list[int], target: list[int]) -> None:
        """`target += a (mod 2^32)`: Gidney's adder. `carries[i]` holds the carry into bit i + 1."""
        t = self.carries
        for i in range(WORD - 1):
            if i:
                self.gates += [('CX', t[i - 1], a[i]), ('CX', t[i - 1], target[i])]
            self.gates.append(('AND', a[i], target[i], t[i]))
            if i:
                self.gates.append(('CX', t[i - 1], t[i]))
        self.gates += [('CX', a[WORD - 1], target[WORD - 1]), ('CX', t[WORD - 2], target[WORD - 1])]
        for i in reversed(range(WORD - 1)):
            if i:
                self.gates.append(('CX', t[i - 1], t[i]))
            self.gates += [('UNAND', a[i], target[i], t[i]), ('CX', a[i], target[i])]
            if i:
                self.gates += [('CX', t[i - 1], target[i]), ('CX', t[i - 1], a[i])]

    def ch_into_tmp(self, x: list[int], y: list[int], z: list[int], *, undo: bool = False) -> None:
        """`tmp ^= Ch(x, y, z)` through a temporary AND per bit, or its removal."""
        for xi, yi, zi, ti, ai in zip(x, y, z, self.tmp, self.and_row):
            if not undo:
                self.gates += [('CX', zi, yi), ('AND', xi, yi, ai), ('CX', zi, yi), ('CX', ai, ti), ('CX', zi, ti)]
            else:
                self.gates += [('CX', zi, ti), ('CX', ai, ti), ('CX', zi, yi), ('UNAND', xi, yi, ai), ('CX', zi, yi)]

    def maj_into_tmp(self, x: list[int], y: list[int], z: list[int], *, undo: bool = False) -> None:
        """`tmp ^= Maj(x, y, z)` through a temporary AND per bit, or its removal."""
        for xi, yi, zi, ti, ai in zip(x, y, z, self.tmp, self.and_row):
            if not undo:
                self.gates += [('CX', xi, yi), ('CX', xi, zi), ('AND', yi, zi, ai), ('CX', xi, zi),
                               ('CX', xi, yi), ('CX', ai, ti), ('CX', xi, ti)]
            else:
                self.gates += [('CX', xi, ti), ('CX', ai, ti), ('CX', xi, yi), ('CX', xi, zi),
                               ('UNAND', yi, zi, ai), ('CX', xi, zi), ('CX', xi, yi)]

    def inverse(self, gate: unitary.Gate) -> unitary.Gate:
        swap = {'AND': 'UNAND', 'UNAND': 'AND'}
        return (swap.get(gate[0], gate[0]), *gate[1:])

    def emit(self, gate: unitary.Gate) -> list[str]:
        name, *qubits = gate
        if name == 'AND':
            x, y, t = qubits
            return [f'CCX q{x} q{y} q{t}']
        if name == 'UNAND':
            # X-basis measurement resets t; a result of 1 leaves a phase of -1 exactly when
            # x AND y, which the conditional CZ cancels.
            x, y, t = qubits
            return [f'HMR q{t} b0', f'CZ q{x} q{y} if b0']
        return super().emit(gate)


def published_counts() -> dict[str, int]:
    """The quantities in qSHA256's benchmarks/results/latest.md, row
    `sha256 compression | 64 | gidney/load/rolling/serial/uncomp`, leaving out the X gates
    that load and clear H. Its T-count column is four times the number of computed ANDs."""
    builder = QSha256MeasuredReconstruction()
    gates = builder.build_gates()
    ands = sum(gate[0] == 'AND' for gate in gates)
    return {
        'qubits': builder.num_qubits,
        'ands': ands,
        't_count': 4 * ands,
        'gates': len(gates) - unitary.IV_LOAD_GATES,
        'toffoli_gates': sum(gate[0] == 'CCX' for gate in gates),
    }


PUBLISHED = {'qubits': 1375, 'ands': 45144, 't_count': 180576, 'gates': 514364, 'toffoli_gates': 0}

if __name__ == '__main__':
    counts = published_counts()
    assert counts == PUBLISHED, f'reconstruction {counts} differs from the published table {PUBLISHED}'
    print(f'{counts}; matches the published table.')
    baseline.main(QSha256MeasuredReconstruction, __file__)
