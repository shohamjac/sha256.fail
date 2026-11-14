"""A variant of the baseline that trades Toffolis for qubits.

The baseline's adder keeps 31 carry qubits and clears them by measurement. This variant
uses the ripple-carry adder of Cuccaro, Draper, Kutin and Moulton (arXiv:quant-ph/0410184),
which stores each carry in the addend itself and needs one extra qubit, at the price of
two Toffolis per bit instead of one.

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

WORD = baseline.WORD


class LowQubitBuilder(baseline.Sha256Builder):

    def __init__(self) -> None:
        super().__init__()
        self.carry = self.b.alloc_qubits(1)[0]

    def add(self, offset: km.array | int, target: km.array, *, subtract: bool = False) -> None:
        if isinstance(offset, int):
            # A constant is written into the temporary, added, and erased. The temporary is
            # free whenever a constant is added.
            ones = [self.tmp[k] for k in range(WORD) if (offset >> k) & 1]
            self.b.x(ones)
            self.add(self.tmp, target, subtract=subtract)
            self.b.x(ones)
            return

        a, s = offset, target
        gates: list[tuple] = []
        carries = [self.carry, *[a[i] for i in range(WORD - 2)]]  # Carry into bit i, for i < 31.
        for i in range(WORD - 1):  # MAJ: a[i] becomes the carry out of bit i.
            gates += [('cx', a[i], s[i]), ('cx', a[i], carries[i]), ('ccx', carries[i], s[i], a[i])]
        gates += [('cx', a[WORD - 1], s[WORD - 1]), ('cx', a[WORD - 2], s[WORD - 1])]  # Top bit: no carry out.
        for i in reversed(range(WORD - 1)):  # UMA: restore a[i], leave the sum bit in s[i].
            gates += [('ccx', carries[i], s[i], a[i]), ('cx', a[i], carries[i]), ('cx', carries[i], s[i])]

        # Every gate is its own inverse, so subtraction is the same gates in reverse order.
        for name, *qubits in (reversed(gates) if subtract else gates):
            getattr(self.b, name)(*qubits)


if __name__ == '__main__':
    baseline.main(LowQubitBuilder, __file__)
