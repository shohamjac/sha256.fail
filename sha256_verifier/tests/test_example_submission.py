"""The baseline circuit in submissions/example, verified against the real problem.

This is the end-to-end test of the verifier on `sha256-compress-v1`. The circuit's
generator was checked against `hashlib` only and never imports the verifier's reference
function, so agreement here is between two independent implementations of SHA-256.
"""

import importlib.util
import io
import json
import pathlib

import kickmix as km
import pytest

from sha_verifier import circuits, problems, verify

ROOT = pathlib.Path(__file__).parents[2]
EXAMPLE = ROOT / 'submissions' / 'example'
PROBLEM = problems.SHA256_COMPRESS_V1


@pytest.fixture(scope='module')
def circuit_bytes() -> bytes:
    return (EXAMPLE / 'circuit.kmb').read_bytes()


@pytest.fixture(scope='module')
def loaded(circuit_bytes) -> circuits.Loaded:
    return circuits.load(circuit_bytes)


def test_passes(circuit_bytes):
    receipt = verify.verify(circuit_bytes, PROBLEM, random_shots=8192, salt='test')
    assert receipt['status'] == 'PASS', receipt['failure']
    assert receipt['cost'] == {'qubits': 831, 'toffoli': 27088.0, 'score': 831 * 27088.0,
                               'toffoli_executed_total': 27088 * 8192, 'shots': 8192}
    assert receipt['verification']['directed_shots'] == 1179
    assert receipt['verification']['full_strength'] is False


def test_generator_does_not_use_the_verifier():
    source = (EXAMPLE / 'build.py').read_text()
    assert 'sha_verifier' not in source.replace('../../sha256_verifier', '')


def test_generator_reproduces_the_committed_circuit(circuit_bytes):
    spec = importlib.util.spec_from_file_location('example_build', EXAMPLE / 'build.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    buffer = io.BytesIO()
    module.Sha256Builder().build().to_file(buffer, format='kmb')
    assert buffer.getvalue() == circuit_bytes


def test_committed_receipt_is_for_this_circuit(circuit_bytes, loaded):
    receipts = [json.loads(p.read_text()) for p in (ROOT / 'results' / PROBLEM.name).glob('*.json')]
    mine = [r for r in receipts if r['circuit']['sha256'] == loaded.sha256]
    assert len(mine) == 1
    receipt = mine[0]
    assert receipt['status'] == 'PASS' and receipt['verification']['full_strength'] is True
    assert receipt['verification']['random_shots'] == 1 << 20
    assert receipt['submission'] == json.loads((EXAMPLE / 'meta.json').read_text())
    assert (receipt['cost']['qubits'], receipt['cost']['toffoli']) == (831, 27088.0)


def _without_line(text: str, index: int) -> bytes:
    lines = text.split('\n')
    del lines[index]
    return '\n'.join(lines).encode()


@pytest.mark.parametrize('name', ['CCX', 'CX', 'CZ', 'X', 'HMR', 'NEG'])
def test_removing_any_one_gate_is_caught(loaded, name):
    """Delete single instructions of each kind from a quarter, half, three quarters and the end.

    The very first gates are left alone: until the first message word is added, round 0
    works on the fixed initial hash value, so some of its gates never do anything (a carry
    that is always zero, say) and removing them gives an equally correct circuit.
    """
    lines = loaded.text.split('\n')
    positions = [i for i, line in enumerate(lines) if line.split(' ')[0] == name]
    assert len(positions) >= 8, name
    n = len(positions)
    for index in (positions[n // 4], positions[n // 2], positions[3 * n // 4], positions[-1]):
        receipt = verify.verify(_without_line(loaded.text, index), PROBLEM, random_shots=4096, salt='mutant')
        assert receipt['status'] == 'FAIL', (name, index, lines[index])
        assert receipt['failure']['stage'] in ('directed', 'random'), receipt['failure']


def test_tampering_with_a_register_is_caught(loaded):
    appended = (loaded.text + 'X q512\n').encode()  # Flip one digest bit at the end.
    failure = verify.verify(appended, PROBLEM, random_shots=256)['failure']
    assert (failure['stage'], failure['code']) == ('directed', 'wrong_output')

    appended = (loaded.text + 'X q0\n').encode()  # Flip one block bit at the end.
    failure = verify.verify(appended, PROBLEM, random_shots=256)['failure']
    assert (failure['stage'], failure['code']) == ('directed', 'input_changed')


def test_text_form_is_the_same_circuit(circuit_bytes, loaded):
    assert circuits.load(loaded.text.encode()).sha256 == loaded.sha256
    assert km.Circuit.from_file(io.BytesIO(circuit_bytes)) == loaded.circuit
