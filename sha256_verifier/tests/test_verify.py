"""The verifier end to end: a correct circuit passes, every broken one is rejected."""

import json
import pathlib

import jsonschema
import pytest

import toy
from sha_verifier import circuits, problems, simulate, verify

SCHEMA = json.loads((pathlib.Path(__file__).parents[1] / 'schema' / 'receipt.schema.json').read_text())


def run(text_or_bytes, problem=toy.PROBLEM, **kwargs) -> dict:
    data = text_or_bytes.encode() if isinstance(text_or_bytes, str) else text_or_bytes
    kwargs.setdefault('workers', 2)
    receipt = verify.verify(data, problem, **kwargs)
    jsonschema.validate(receipt, SCHEMA)
    assert (receipt['status'] == 'PASS') == (receipt['failure'] is None) == (receipt['cost'] is not None)
    return receipt


# A correct circuit.


def test_correct_circuit_passes():
    receipt = run(toy.GOOD)
    assert receipt['status'] == 'PASS'
    assert receipt['problem'] == 'toy-add4-v0'
    assert receipt['cost'] == {'qubits': toy.QUBITS, 'toffoli': 3.0, 'score': 42.0,
                               'toffoli_executed_total': 3 * 4096, 'shots': 4096}
    assert receipt['circuit']['qubits'] == toy.QUBITS
    assert receipt['circuit']['toffoli_static'] == toy.TOFFOLIS
    assert receipt['circuit']['instruction_counts']['HMR'] == 2
    assert receipt['verification']['directed_shots'] == len(toy.DIRECTED)
    assert receipt['verification']['random_shots'] == 4096
    assert receipt['verification']['full_strength'] is True


def test_fewer_shots_is_not_full_strength():
    receipt = run(toy.GOOD, random_shots=256)
    assert receipt['status'] == 'PASS' and receipt['verification']['full_strength'] is False
    assert receipt['cost']['shots'] == 256


def test_binary_and_text_submissions_are_the_same_circuit():
    text = run(toy.GOOD)
    binary = run(toy.kmb(toy.GOOD))
    decorated = run('# header\n' + toy.GOOD.replace('CX q4 q8', '   CX q4 q8   # copy'))
    assert text['circuit']['sha256'] == binary['circuit']['sha256'] == decorated['circuit']['sha256']
    assert len({r['circuit']['file_sha256'] for r in (text, binary, decorated)}) == 3
    assert text['verification']['seed'] == binary['verification']['seed']
    assert text['cost'] == binary['cost'] == decorated['cost']


def test_classical_bits_do_not_leak_between_batches():
    """If bits survived from one batch to the next, the second batch would dirty q12."""
    leaky = toy.GOOD + 'X q12 if b7\nBIT_STORE1 b7\n'
    assert run(leaky)['status'] == 'PASS'


def test_conditional_toffolis_count_only_when_executed():
    """Two extra Toffolis that cancel, under a coin flip: C is about 4, not 3 or 5."""
    text = toy.GOOD + 'R q14\nHMR q14 b5\nCCX q0 q1 q14 if b5\nCCX q0 q1 q14 if b5\n'
    receipt = run(text)
    assert receipt['status'] == 'PASS'
    assert receipt['circuit']['toffoli_static'] == 5
    assert 3.9 < receipt['cost']['toffoli'] < 4.1
    assert receipt['cost']['toffoli_executed_total'] % 2 == 0
    assert receipt['cost']['score'] == receipt['cost']['qubits'] * receipt['cost']['toffoli']


# Replay.


def test_same_salt_replays_the_same_receipt():
    first, again = run(toy.GOOD, salt='s1'), run(toy.GOOD, salt='s1')
    assert verify.reproducible_part(first) == verify.reproducible_part(again)
    assert set(first) - set(verify.reproducible_part(first)) == {'run'}


def test_failing_run_replays_the_same_witness():
    first, again = run(toy.RARE_WRONG_OUTPUT, salt='s1'), run(toy.RARE_WRONG_OUTPUT, salt='s1')
    assert first['status'] == 'FAIL' and first['failure']['stage'] == 'random'
    assert verify.reproducible_part(first) == verify.reproducible_part(again)


def test_replay_is_the_same_on_every_machine():
    """Values recorded on one machine. They cover the circuit hash, the seed, the random
    inputs and Kickmix's measurement outcomes (which shot of a phase bug flips first)."""
    good = run(toy.GOOD, salt='pin')
    assert good['circuit']['sha256'] == 'c8a7eef253e900d2edb612a9d9162e485f1f9ed86fe7559aaaddbfa6f7e441b8'
    assert good['verification']['seed'] == 'bee6a6966334fd4ea4c0caf930440a3de24193dee6840e4fd1c3365bd566ab28'

    bad = run(toy.without('CZ q9 q1 if b0'), salt='pin')
    assert bad['verification']['seed'] == '3506870657a6d4bb6a634386dac3644a8a92879294a2c42da0fecc6bf18412a3'
    assert bad['failure'] == {
        'stage': 'random', 'code': 'phase_flipped', 'message': 'The shot ended with a flipped phase.',
        'shot': 3, 'inputs': {'a': '02', 'b': '07'},
        'failing_shots': {'wrong_output': 0, 'input_changed': 0, 'dirty_scratch': 0, 'phase_flipped': 30},
    }


def test_result_does_not_depend_on_worker_count():
    for text in (toy.GOOD, toy.RARE_WRONG_OUTPUT, toy.RARE_PHASE_FLIP):
        parts = [verify.reproducible_part(run(text, salt='w', workers=w, random_shots=3 * 4096))
                 for w in (1, 2, 5)]
        assert parts[0] == parts[1] == parts[2]


def test_salt_changes_the_tests():
    a, b = run(toy.RARE_WRONG_OUTPUT, salt='a'), run(toy.RARE_WRONG_OUTPUT, salt='b')
    assert a['verification']['seed'] != b['verification']['seed']
    assert (a['failure']['shot'], a['failure']['inputs']) != (b['failure']['shot'], b['failure']['inputs'])


def test_tests_depend_on_the_circuit():
    """Adding a no-op changes the circuit hash and therefore the seed."""
    assert run(toy.GOOD)['verification']['seed'] != run(toy.GOOD + 'X q0\nX q0\n')['verification']['seed']


# Circuits that must be rejected.

EXTRA_REGISTER = toy.GOOD + 'APPEND_TO_REGISTER q12 r3\nREGISTER r3 "extra"\n'
SHORT_REGISTER = toy.without('APPEND_TO_REGISTER q11 r2')
OVERLAPPING = toy.GOOD.replace('APPEND_TO_REGISTER q11 r2', 'APPEND_TO_REGISTER q0 r2')
REPEATED_QUBIT = toy.GOOD.replace('APPEND_TO_REGISTER q11 r2', 'APPEND_TO_REGISTER q10 r2')
BIT_IN_REGISTER = toy.GOOD.replace('APPEND_TO_REGISTER q11 r2', 'APPEND_TO_REGISTER b0 r2')
WRONG_NAME = toy.GOOD.replace('"sum"', '"total"')
WRONG_ORDER = toy.GOOD.replace('"a"', '"tmp"').replace('"b"', '"a"').replace('"tmp"', '"b"')
UNNAMED = toy.without('REGISTER r2 "sum"')
MISSING_REGISTER = toy.BODY

REJECTED = {
    # name: (circuit, stage, code)
    'one wrong output bit': (toy.GOOD + 'X q8\n', 'directed', 'wrong_output'),
    'input not restored': (toy.GOOD + 'X q0\n', 'directed', 'input_changed'),
    'input measured away': (toy.GOOD + 'HMR q0 b5\n', 'directed', 'input_changed'),
    'dirty scratch': (toy.GOOD + 'X q12\n', 'directed', 'dirty_scratch'),
    'conditional reset that does not happen': (toy.GOOD + 'X q12\nBIT_STORE0 b9\nR q12 if b9\n',
                                               'directed', 'dirty_scratch'),
    'stray global phase': (toy.GOOD + 'NEG\n', 'directed', 'phase_flipped'),
    'reset of a dirty qubit': (toy.GOOD + 'X q12\nR q12\n', 'directed', 'phase_flipped'),
    'missing gate': (toy.without('CX q12 q11'), 'random', 'wrong_output'),
    'does nothing': (toy.REGISTERS, 'directed', 'wrong_output'),
    'missing phase fixup': (toy.without('CZ q9 q1 if b0'), 'random', 'phase_flipped'),
    'wrong on 2 of 256 inputs': (toy.RARE_WRONG_OUTPUT, 'random', 'wrong_output'),
    'phase flipped on 2 of 256 inputs': (toy.RARE_PHASE_FLIP, 'random', 'phase_flipped'),
    'rotation present': (toy.GOOD + 'Z_POW q0 2.0\n', 'structure', 'instruction_not_allowed'),
    'extra register': (EXTRA_REGISTER, 'structure', 'wrong_registers'),
    'missing register': (MISSING_REGISTER, 'structure', 'wrong_registers'),
    'wrong register name': (WRONG_NAME, 'structure', 'wrong_registers'),
    'registers in the wrong order': (WRONG_ORDER, 'structure', 'wrong_registers'),
    'unnamed register': (UNNAMED, 'structure', 'wrong_registers'),
    'register too short': (SHORT_REGISTER, 'structure', 'wrong_register_size'),
    'registers share a qubit': (OVERLAPPING, 'structure', 'register_overlap'),
    'register repeats a qubit': (REPEATED_QUBIT, 'structure', 'register_overlap'),
    'classical bit in a register': (BIT_IN_REGISTER, 'structure', 'register_has_bits'),
    'empty file': ('', 'structure', 'wrong_registers'),
    'aliased operands': (toy.GOOD + 'CCX q0 q0 q8\n', 'load', 'unreadable'),
    'unknown instruction': (toy.GOOD + 'H q0\n', 'load', 'unreadable'),
    'not a circuit': (b'\x00\x01\x02 garbage \xff', 'load', 'unreadable'),
    'truncated binary': (toy.kmb(toy.GOOD)[:-7], 'load', 'unreadable'),
    'binary with trailing bytes': (toy.kmb(toy.GOOD) + b'extra', 'load', 'unreadable'),
    'too many qubits': (toy.GOOD + 'X q70000\nX q70000\n', 'load', 'too_many_qubits'),
}


@pytest.mark.parametrize('name', REJECTED)
def test_rejected(name):
    circuit, stage, code = REJECTED[name]
    receipt = run(circuit)
    assert receipt['status'] == 'FAIL'
    assert (receipt['failure']['stage'], receipt['failure']['code']) == (stage, code), receipt['failure']
    assert receipt['cost'] is None


def test_mutants_differ_from_the_good_circuit_only_as_intended():
    """Faults placed in the random stage really do pass every directed test."""
    for name, (circuit, stage, _) in REJECTED.items():
        if stage == 'random':
            loaded = circuits.load(circuit.encode())
            layout = circuits.check_structure(loaded, toy.PROBLEM)
            _, failure = simulate.run_directed(loaded.circuit, layout, toy.PROBLEM, b'\x00' * 32)
            assert failure is None, name


def test_failure_carries_a_replayable_witness():
    failure = run(toy.RARE_WRONG_OUTPUT)['failure']
    a, b = int(failure['inputs']['a'], 16), int(failure['inputs']['b'], 16)
    assert a == 15 and b % 8 == 7  # Exactly the inputs the fault was built to break.
    assert 0 <= failure['shot'] < 4096
    assert failure['failing_shots']['wrong_output'] >= 1
    assert failure['failing_shots']['input_changed'] == 0


def test_directed_failure_reports_the_directed_test_index():
    # Flip sum[0] only when a == 5 and b == 10, which is directed test 3.
    text = toy.GOOD + 'X q1\nX q3\nX q4\nX q6\n' + toy._RARE.format(action='CX q20 q8').replace(
        'CCX q18 q6 q20', 'CCX q18 q6 q19\nCCX q19 q7 q20', 1).replace(
        'CCX q18 q6 q20', 'CCX q19 q7 q20\nCCX q18 q6 q19') + 'X q1\nX q3\nX q4\nX q6\n'
    failure = run(text)['failure']
    assert (failure['stage'], failure['code'], failure['shot']) == ('directed', 'wrong_output', 3)
    assert failure['inputs'] == {'a': '05', 'b': '0a'}


def test_load_failure_still_identifies_the_file():
    receipt = run(b'not a circuit \xff')
    assert receipt['circuit']['sha256'] is None and len(receipt['circuit']['file_sha256']) == 64
    assert receipt['verification']['seed'] is None and receipt['verification']['directed_shots'] is None


def test_impossible_toffoli_count_is_rejected(monkeypatch):
    real = simulate.run_random

    def inflated(*args, **kwargs):
        total, failure = real(*args, **kwargs)
        return total + 1, failure

    monkeypatch.setattr(simulate, 'run_random', inflated)
    receipt = run(toy.GOOD)
    assert receipt['status'] == 'FAIL'
    assert (receipt['failure']['stage'], receipt['failure']['code']) == ('accounting', 'toffoli_count_inconsistent')


def test_caller_mistakes_raise():
    with pytest.raises(ValueError):
        verify.verify(toy.GOOD.encode(), toy.PROBLEM, random_shots=100)
    with pytest.raises(ValueError):
        verify.verify(toy.GOOD.encode(), toy.PROBLEM, workers=0)


# The real problem. No correct SHA-256 circuit exists yet, so only rejection is tested here.


def test_sha256_do_nothing_circuit_is_rejected():
    receipt = run(toy.sha256_do_nothing(), problem=problems.SHA256_COMPRESS_V1, random_shots=256)
    assert receipt['status'] == 'FAIL'
    assert (receipt['failure']['stage'], receipt['failure']['code']) == ('directed', 'wrong_output')
    assert receipt['failure']['inputs'] == {'block': '00' * 64}
    assert receipt['circuit']['qubits'] == 768
    assert receipt['verification']['directed_shots'] == 1179


def test_sha256_wrong_shape_is_rejected():
    text = toy.sha256_do_nothing().replace('APPEND_TO_REGISTER q767 r1\n', '')
    receipt = run(text, problem=problems.SHA256_COMPRESS_V1, random_shots=256)
    assert (receipt['failure']['stage'], receipt['failure']['code']) == ('structure', 'wrong_register_size')


def test_toy_circuit_is_not_a_sha256_circuit():
    receipt = run(toy.GOOD, problem=problems.SHA256_COMPRESS_V1, random_shots=256)
    assert (receipt['failure']['stage'], receipt['failure']['code']) == ('structure', 'wrong_registers')
