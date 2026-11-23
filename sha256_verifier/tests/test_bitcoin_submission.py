"""The baseline circuit in submissions/bitcoin-mining-baseline, verified against `bitcoin-mining-v1`.

This is the end-to-end test of the verifier on that problem. The circuit's generator was
checked against `hashlib` only and never imports the verifier's reference function, so
agreement here is between two independent implementations. Faulty variants of the
generator must each be caught.
"""

import importlib.util
import io
import json
import pathlib

import jsonschema
import pytest

from sha_verifier import bitcoin, circuits, problems, simulate, submission, verify

ROOT = pathlib.Path(__file__).parents[2]
NAME = 'bitcoin-mining-baseline'
DIRECTORY = ROOT / 'submissions' / NAME
PROBLEM = problems.BITCOIN_MINING_V1
SCHEMA = json.loads((pathlib.Path(__file__).parents[1] / 'schema' / 'receipt.schema.json').read_text())

QUBITS, TOFFOLIS = 2000, 262158
DIRECTED_SHOTS = 2848


def _load_generator():
    spec = importlib.util.spec_from_file_location('build_bitcoin_mining_baseline', DIRECTORY / 'build.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = _load_generator()


def kmb(builder) -> bytes:
    buffer = io.BytesIO()
    builder().build().to_file(buffer, format='kmb')
    return buffer.getvalue()


def run(data: bytes, **kwargs) -> dict:
    kwargs.setdefault('workers', 2)
    kwargs.setdefault('random_shots', 1024)
    receipt = verify.verify(data, PROBLEM, salt='test', **kwargs)
    jsonschema.validate(receipt, SCHEMA)
    return receipt


@pytest.fixture(scope='module')
def circuit_bytes() -> bytes:
    return circuits.decompress(submission.circuit_path(DIRECTORY).read_bytes())


def test_directory_is_well_formed():
    meta, circuit = submission.check(DIRECTORY)
    assert meta['problem'] == PROBLEM.name and meta['kind'] == 'baseline'
    assert meta['path'] == f'submissions/{NAME}' and circuit.name == 'circuit.kmb.zst'


def test_passes(circuit_bytes):
    receipt = run(circuit_bytes, random_shots=8192)
    assert receipt['status'] == 'PASS', receipt['failure']
    assert receipt['problem'] == 'bitcoin-mining-v1'
    assert receipt['cost'] == {'qubits': QUBITS, 'toffoli': float(TOFFOLIS), 'score': QUBITS * float(TOFFOLIS),
                               'toffoli_executed_total': TOFFOLIS * 8192, 'shots': 8192}
    assert receipt['circuit']['toffoli_static'] == TOFFOLIS
    assert receipt['verification']['directed_shots'] == DIRECTED_SHOTS
    assert receipt['verification']['full_strength'] is False


def test_no_toffoli_is_under_a_classical_condition(circuit_bytes):
    """So the executed count and the count in the circuit text are the same number."""
    assert circuits.load(circuit_bytes).summary.conditional_total(problems.TOFFOLI_LIKE) == 0


def test_generator_reproduces_the_committed_circuit(circuit_bytes):
    assert kmb(build.BitcoinOracleBuilder) == circuit_bytes


def test_generator_does_not_use_the_verifier():
    source = (DIRECTORY / 'build.py').read_text()
    assert 'sha_verifier' not in source.replace('../../sha256_verifier', '').replace('sha256_verifier/docs', '')


def test_committed_receipt_matches_the_submission(circuit_bytes):
    """The receipt is recorded when the submission is merged; until then there is none to check."""
    sha256 = circuits.load(circuit_bytes).sha256
    path = ROOT / 'results' / PROBLEM.name / f'{sha256}.json'
    if not path.exists():
        pytest.skip('No receipt has been recorded for this circuit yet.')
    receipt = json.loads(path.read_text())
    assert receipt['submission'] == json.loads((DIRECTORY / 'meta.json').read_text())
    assert receipt['status'] == 'PASS' and receipt['verification']['full_strength'] is True
    assert len(receipt['verification']['salt']) == 64
    assert (receipt['cost']['qubits'], receipt['cost']['toffoli']) == (QUBITS, float(TOFFOLIS))


# Faulty variants of the generator.


class NeverFlips(build.BitcoinOracleBuilder):
    def phase(self, digest):
        pass


class IgnoresMask(build.BitcoinOracleBuilder):
    def apply_mask(self, digest):
        pass


class IgnoresTopBit(build.BitcoinOracleBuilder):
    def compared(self, digest):
        return super().compared(digest)[:95]


class AcceptsTie(build.BitcoinOracleBuilder):
    """Bitcoin's own rule, which differs from the problem's only when the hash equals the target."""
    OR_EQUAL = True


@pytest.mark.parametrize('builder,stage', [
    (NeverFlips, 'directed'),      # The first real block is missed.
    (IgnoresMask, 'directed'),     # A real block's one-bit masks catch it.
    (IgnoresTopBit, 'directed'),   # So does the one-bit mask on the top bit.
    (AcceptsTie, 'random'),        # Only the random tests' ties can.
], ids=['never flips', 'ignores mask', 'ignores top bit', 'accepts a tie'])
def test_faulty_oracles_are_caught(builder, stage):
    receipt = run(kmb(builder))
    assert receipt['status'] == 'FAIL'
    assert (receipt['failure']['stage'], receipt['failure']['code']) == (stage, 'wrong_phase')
    assert set(receipt['failure']['inputs']) == {name for name, _, _ in bitcoin.REGISTERS}


def test_a_tie_passes_every_real_block():
    """Real blocks cannot tell `<` from `<=`."""
    loaded = circuits.load(kmb(AcceptsTie))
    layout = circuits.check_structure(loaded, PROBLEM)
    count, failure = simulate.run_directed(loaded.circuit, layout, PROBLEM, b'\x01' * 32)
    assert count == DIRECTED_SHOTS and failure is None


def test_changing_the_search_register_is_caught():
    class LeavesNonceChanged(build.BitcoinOracleBuilder):
        def build(self):
            self.b.x(self.nonce[31])
            return super().build()

    failure = run(kmb(LeavesNonceChanged), random_shots=256)['failure']
    assert (failure['stage'], failure['code']) == ('directed', 'input_changed')
