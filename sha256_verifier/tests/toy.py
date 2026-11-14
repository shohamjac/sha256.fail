"""A small problem and a correct circuit for it, for testing the verifier end to end.

The problem is 4-bit addition: `sum = a + b (mod 16)`. Its directed tests are deliberately
sparse so that some faults are only reachable by random tests.
"""

from __future__ import annotations

import io

import kickmix as km
import numpy as np

from sha_verifier.problems import ProblemSpec, RegisterBits, RegisterSpec

DIRECTED = [(0, 0), (15, 0), (0, 15), (5, 10), (8, 8)]


def _to_bits(values) -> np.ndarray:
    return ((np.asarray(values)[None, :] >> np.arange(4)[:, None]) & 1).astype(bool)


def _from_bits(register: np.ndarray) -> np.ndarray:
    return (register.astype(np.int64) << np.arange(4)[:, None]).sum(axis=0)


def _reference(inputs: RegisterBits) -> RegisterBits:
    return {'sum': _to_bits((_from_bits(inputs['a']) + _from_bits(inputs['b'])) % 16)}


def _directed() -> RegisterBits:
    return {'a': _to_bits([a for a, _ in DIRECTED]), 'b': _to_bits([b for _, b in DIRECTED])}


PROBLEM = ProblemSpec(
    name='toy-add4-v0',
    title='4-bit addition',
    registers=(RegisterSpec('a', 4, 'input'), RegisterSpec('b', 4, 'input'), RegisterSpec('sum', 4, 'output')),
    reference=_reference,
    directed_inputs=_directed,
    random_shots=4096,
)

REGISTERS = """\
APPEND_TO_REGISTER q0 r0
APPEND_TO_REGISTER q1 r0
APPEND_TO_REGISTER q2 r0
APPEND_TO_REGISTER q3 r0
REGISTER r0 "a"
APPEND_TO_REGISTER q4 r1
APPEND_TO_REGISTER q5 r1
APPEND_TO_REGISTER q6 r1
APPEND_TO_REGISTER q7 r1
REGISTER r1 "b"
APPEND_TO_REGISTER q8 r2
APPEND_TO_REGISTER q9 r2
APPEND_TO_REGISTER q10 r2
APPEND_TO_REGISTER q11 r2
REGISTER r2 "sum"
"""

# Copy b into sum, then sum += a with two carry qubits (q12, q13) cleared by measurement.
BODY = """\
CX q4 q8
CX q5 q9
CX q6 q10
CX q7 q11
CX q3 q11
R q12
CCX q8 q0 q12
CX q12 q1
CX q12 q9
R q13
CCX q1 q9 q13
CX q13 q12
CX q12 q2
CX q12 q10
CX q12 q11
CCX q10 q2 q11
CX q2 q10
CX q12 q10
CX q12 q2
CX q13 q12
HMR q13 b0
CZ q9 q1 if b0
CX q1 q9
CX q12 q9
CX q12 q1
HMR q12 b0
CZ q8 q0 if b0
CX q0 q8
"""

GOOD = REGISTERS + BODY
QUBITS = 14
TOFFOLIS = 3

# Sets q20 when a == 15 and b mod 8 == 7 (2 of the 256 inputs, none of them directed),
# using scratch q14..q19; `{action}` acts on q20; then everything is uncomputed.
_RARE = """\
CCX q0 q1 q14
CCX q14 q2 q15
CCX q15 q3 q16
CCX q16 q4 q17
CCX q17 q5 q18
CCX q18 q6 q20
{action}
CCX q18 q6 q20
CCX q17 q5 q18
CCX q16 q4 q17
CCX q15 q3 q16
CCX q14 q2 q15
CCX q0 q1 q14
"""
RARE_WRONG_OUTPUT = GOOD + _RARE.format(action='CX q20 q8')
RARE_PHASE_FLIP = GOOD + _RARE.format(action='Z q20')


def without(line: str, text: str = GOOD) -> str:
    """`text` with one line removed; the line must occur exactly once."""
    assert text.count(line + '\n') == 1, line
    return text.replace(line + '\n', '')


def kmb(text: str) -> bytes:
    buffer = io.BytesIO()
    km.Circuit(text).to_file(buffer, format='kmb')
    return buffer.getvalue()


def sha256_do_nothing() -> str:
    """A circuit with the registers of sha256-compress-v1 and no operations."""
    lines = [f'APPEND_TO_REGISTER q{i} r0' for i in range(512)] + ['REGISTER r0 "block"']
    lines += [f'APPEND_TO_REGISTER q{512 + i} r1' for i in range(256)] + ['REGISTER r1 "digest"']
    return '\n'.join(lines) + '\n'


