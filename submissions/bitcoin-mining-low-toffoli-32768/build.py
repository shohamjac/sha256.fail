"""Builds ../bitcoin-mining-low-toffoli on at most 32768 qubits.

    |extranonce, nonce>  ->  (-1)^f |extranonce, nonce>

That circuit keeps the carries of its additions in qubits of their own, which makes the
backward half free of Toffolis wherever a carry was kept, and it uses all 65,536 qubits
the problem allows. This is the same generator with fewer qubits to keep carries in: one
Toffoli more for every qubit taken away. See ../bitcoin-mining-low-toffoli/build.py.

Usage, from this directory:

    uv run --project ../../sha256_verifier python build.py
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

QUBITS = 32768

_HERE = pathlib.Path(__file__).parent
_spec = importlib.util.spec_from_file_location(
    'low_toffoli_build', _HERE.parent / 'bitcoin-mining-low-toffoli' / 'build.py')
low_toffoli = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = low_toffoli
_spec.loader.exec_module(low_toffoli)

if __name__ == '__main__':
    low_toffoli.main(QUBITS, _HERE)
