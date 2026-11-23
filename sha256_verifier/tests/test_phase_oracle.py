"""Problems whose answer is a phase, and registers made of classical bits."""

import json
import pathlib

import jsonschema
import kickmix as km
import numpy as np
import pytest

import toy
from sha_verifier import circuits, problems, sampling, simulate, verify

SCHEMA = json.loads((pathlib.Path(__file__).parents[1] / 'schema' / 'receipt.schema.json').read_text())
PROBLEM = toy.PHASE_PROBLEM


def run(text: str, **kwargs) -> dict:
    receipt = verify.verify(text.encode(), PROBLEM, workers=2, **kwargs)
    jsonschema.validate(receipt, SCHEMA)
    return receipt


def structure_error(text: str) -> str:
    with pytest.raises(circuits.Rejected) as caught:
        circuits.check_structure(circuits.load(text.encode()), PROBLEM)
    assert caught.value.stage == 'structure'
    return caught.value.code


def test_correct_oracle_passes():
    receipt = run(toy.PHASE_GOOD)
    assert receipt['status'] == 'PASS', receipt['failure']
    assert receipt['cost']['qubits'] == 3 and receipt['cost']['toffoli'] == 0
    assert receipt['verification']['directed_shots'] == 16


def test_the_tests_expect_both_phases():
    flips = PROBLEM.phase(sampling.random_inputs(PROBLEM, b'\x05' * 32, 0, 4096))
    assert 1000 < flips.sum() < 2000  # (x0 and t0) xor (x1 and x2 and t1) holds for 5/16 of inputs.


@pytest.mark.parametrize('text', [
    toy.PHASE_REGISTERS,                                   # Never flips.
    toy.PHASE_GOOD + 'NEG\n',                              # Always the opposite.
    toy.PHASE_REGISTERS + 'Z q0 if b0\n',                  # Misses one term.
    toy.PHASE_REGISTERS + 'Z q0\nCZ q1 q2 if b1\n',        # Ignores a classical input.
], ids=['never flips', 'always opposite', 'missing term', 'ignores classical input'])
def test_wrong_phase_is_caught(text):
    receipt = run(text)
    assert receipt['status'] == 'FAIL'
    failure = receipt['failure']
    assert failure['code'] == 'wrong_phase'
    assert failure['message'] == 'The phase was flipped when it must not be, or not flipped when it must be.'
    assert list(failure['failing_shots']) == ['wrong_output', 'input_changed', 'dirty_scratch', 'wrong_phase']
    assert failure['failing_shots']['wrong_phase'] > 0
    assert set(failure['inputs']) == {'x', 't'}


def test_classical_inputs_may_end_in_any_state():
    assert run(toy.PHASE_GOOD + 'BIT_INVERT b0\nBIT_STORE1 b1\n')['status'] == 'PASS'


def test_qubit_inputs_must_be_restored():
    failure = run(toy.PHASE_GOOD + 'X q1\n')['failure']
    assert failure['code'] == 'input_changed'


def test_scratch_must_be_clean():
    failure = run(toy.PHASE_GOOD + 'X q5\n')['failure']
    assert failure['code'] == 'dirty_scratch'


def test_problems_without_a_phase_keep_their_checks():
    assert simulate.checks(toy.PROBLEM) == ('wrong_output', 'input_changed', 'dirty_scratch', 'phase_flipped')
    assert simulate.checks(problems.SHA256_COMPRESS_V1) == simulate.CHECKS


def test_layout_has_bits_for_a_classical_register():
    layout = circuits.check_structure(circuits.load(toy.PHASE_GOOD.encode()), PROBLEM)
    assert list(layout.registers['x']) == [km.q(0), km.q(1), km.q(2)]
    assert list(layout.registers['t']) == [km.b(0), km.b(1)]
    assert len(layout.scratch) == 0


def test_a_qubit_and_a_bit_may_share_an_index():
    """q0 is in `x` and b0 is in `t`: they are different things, and the good circuit has both."""
    circuits.check_structure(circuits.load(toy.PHASE_GOOD.encode()), PROBLEM)


def test_structure_errors():
    good = toy.PHASE_GOOD
    assert structure_error(good.replace('APPEND_TO_REGISTER b1 r1', 'APPEND_TO_REGISTER q7 r1')) == 'register_has_qubits'
    assert structure_error(good.replace('APPEND_TO_REGISTER q2 r0', 'APPEND_TO_REGISTER b7 r0')) == 'register_has_bits'
    assert structure_error(good.replace('APPEND_TO_REGISTER b1 r1\n', '')) == 'wrong_register_size'
    assert structure_error(good.replace('APPEND_TO_REGISTER b1 r1', 'APPEND_TO_REGISTER b0 r1')) == 'register_overlap'


def test_wrong_size_message_names_the_right_thing():
    text = toy.PHASE_GOOD.replace('APPEND_TO_REGISTER b1 r1\n', '')
    with pytest.raises(circuits.Rejected, match="'t' must have 2 bits, has 1"):
        circuits.check_structure(circuits.load(text.encode()), PROBLEM)


def test_a_classical_register_cannot_be_an_output():
    with pytest.raises(ValueError, match='must be an input'):
        problems.RegisterSpec('out', 4, 'output', 'bit')


def test_uniform_random_inputs_fill_classical_registers_too():
    inputs = sampling.random_inputs(PROBLEM, b'\x06' * 32, 0, 4096)
    assert inputs['x'].shape == (3, 4096) and inputs['t'].shape == (2, 4096)
    assert all(0.4 < row.mean() < 0.6 for row in np.concatenate([inputs['x'], inputs['t']]))
