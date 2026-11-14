import io

import kickmix as km
import pytest

import toy
from sha_verifier import kmx

SAMPLE = """
# A comment line.
APPEND_TO_REGISTER q0 r0
APPEND_TO_REGISTER b3 r0
REGISTER r0 "mix"
APPEND_TO_REGISTER q1 r1
DEBUG_PRINT q0
DEBUG_PRINT b1 if b0
DEBUG_PRINT
INFO_TAG "a\\Qb"
PUSH_CONDITION if b0
    CCX q0 q1 q2 if b1   # Indented, with a comment.
    CX q0 q1
POP_CONDITION
CCX q0 q1 q2
NEG if b2
HMR q3 b4 if b2
CSWAP q0 q1 q7
"""


def test_walk_counts_and_registers():
    summary = kmx.walk(SAMPLE)
    assert summary.counts == {'DEBUG_PRINT': 3, 'INFO_TAG': 1, 'PUSH_CONDITION': 1, 'CCX': 2, 'CX': 1,
                              'POP_CONDITION': 1, 'NEG': 1, 'HMR': 1, 'CSWAP': 1}
    assert summary.num_operations == 12
    assert summary.num_qubits == 8 and summary.num_bits == 5
    assert summary.registers == {
        0: kmx.Register('mix', (('q', 0), ('b', 3))),
        1: kmx.Register(None, (('q', 1),)),
    }
    assert summary.instructions >= {'CCX', 'REGISTER', 'APPEND_TO_REGISTER'}


def test_walk_tracks_what_is_conditional():
    summary = kmx.walk(SAMPLE)
    toffoli = frozenset({'CCX', 'CCZ', 'CSWAP'})
    assert summary.total(toffoli) == 3
    assert summary.conditional_total(toffoli) == 1  # Only the CCX inside the pushed block.
    assert summary.conditional_counts['CX'] == 1  # No `if` of its own, but inside the block.
    assert summary.conditional_counts['NEG'] == 1


def test_pop_on_an_empty_stack_does_not_make_later_operations_conditional():
    summary = kmx.walk('POP_CONDITION\nCCX q0 q1 q2\n')
    assert summary.conditional_counts.get('CCX', 0) == 0


@pytest.mark.parametrize('text', [SAMPLE, toy.GOOD, toy.RARE_WRONG_OUTPUT, 'X q5000', '', 'Z_POW q0 -0.25 if b1'])
def test_walk_agrees_with_kickmix(text):
    circuit = km.Circuit(text)
    summary = kmx.walk(text)
    assert summary.counts == dict(circuit.operation_statistics())
    assert summary.num_qubits == circuit.num_qubits
    assert summary.num_bits == circuit.num_bits
    assert summary.num_operations == len(circuit)
    assert summary.total(frozenset({'CCX', 'CCZ', 'CSWAP'})) == circuit.operation_statistics().num_toffoli_like


def test_walk_reads_what_kickmix_writes():
    buffer = io.BytesIO()
    km.Circuit(SAMPLE).to_file(buffer, format='kmx')
    assert kmx.walk(buffer.getvalue().decode()) == kmx.walk(SAMPLE)


@pytest.mark.parametrize('line', [
    'FOO q0',  # Unknown instruction.
    'x q0',  # Lower case.
    'X',  # Missing target.
    'X q0 q1',  # Too many targets.
    'X b0',  # Wrong kind of target.
    'CX q0 q0',  # Same qubit twice.
    'CCX q0 q1 q0',
    'CX q0 q1 if',  # Dangling condition.
    'CX q0 q1 if q2',  # Condition must be a bit.
    'CX if b0 q0 q1',  # Condition must come last.
    'X q-1',
    'X q01',  # Not a canonical id.
    'X q0 0.5',  # Exponent on a non-rotation.
    'Z_POW q0',  # Rotation without exponent.
    'Z_POW q0 1',  # Exponent needs a decimal point.
    'HMR q0',  # Missing output bit.
    'HMR q0 q1',
    'PUSH_CONDITION',  # Needs a condition.
    'PUSH_CONDITION b0',
    'POP_CONDITION if b0',
    'REGISTER q0',
    'REGISTER r0 "a" if b0',
    'APPEND_TO_REGISTER r0 q0',
    'APPEND_TO_REGISTER q0 r0 if b0',
    'INFO_TAG',
    'INFO_TAG "unterminated',
    'INFO_TAG "bad \\x escape"',
    'X q0 "text"',  # Quoted text where none belongs.
    'DEBUG_PRINT q0 q1',
])
def test_walk_rejects(line):
    with pytest.raises(kmx.KmxError, match='Line 2'):
        kmx.walk('X q9\n' + line + '\n')


def test_register_cannot_be_named_twice():
    with pytest.raises(kmx.KmxError):
        kmx.walk('REGISTER r0 "a"\nREGISTER r0 "b"\n')
