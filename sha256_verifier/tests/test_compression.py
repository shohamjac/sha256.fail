"""Circuit files stored zstd-compressed: reading them safely, packing them, and the rule that
large submissions must use them."""

import hashlib
import json

import pytest

import toy
from sha_verifier import circuits, cli, problems, submission, verify

LIMITS = circuits.Limits(max_file_bytes=4096)


@pytest.fixture(autouse=True)
def toy_problem(monkeypatch):
    monkeypatch.setitem(problems.PROBLEMS, toy.PROBLEM.name, toy.PROBLEM)


def reproducible(data: bytes) -> dict:
    return verify.reproducible_part(verify.verify(data, toy.PROBLEM, salt='zst', random_shots=256, workers=1))


@pytest.mark.parametrize('raw', [toy.kmb(toy.GOOD), toy.GOOD.encode()], ids=['kmb', 'kmx'])
def test_compressed_file_gives_the_same_receipt(raw):
    """Down to the file hash, which is of the decompressed file, so compressing an already
    committed circuit leaves its receipt valid."""
    packed = circuits.pack(raw)
    assert packed != raw and circuits.decompress(packed) == raw
    assert reproducible(packed) == reproducible(raw)
    assert reproducible(packed)['status'] == 'PASS'


def test_uncompressed_data_passes_through():
    raw = toy.kmb(toy.GOOD)
    assert circuits.decompress(raw) is raw


@pytest.mark.parametrize('data,fragment', [
    (circuits.pack(toy.kmb(toy.GOOD))[:-5], 'truncated'),
    (circuits.pack(toy.kmb(toy.GOOD)) + b'extra', 'single zstd frame'),
    (circuits.pack(toy.kmb(toy.GOOD)) * 2, 'single zstd frame'),
    (circuits.ZSTD_MAGIC + b'x' * 40, 'not valid zstd'),
    (circuits.pack(circuits.pack(toy.kmb(toy.GOOD))), 'compressed twice'),
], ids=['truncated', 'trailing bytes', 'two frames', 'garbage after the magic number', 'compressed twice'])
def test_malformed_compressed_files_are_rejected(data, fragment):
    with pytest.raises(circuits.Rejected, match=fragment) as caught:
        circuits.decompress(data)
    assert (caught.value.stage, caught.value.code) == ('load', 'unreadable')


def test_decompressed_size_is_limited():
    """A small file that would expand past the limit is stopped at the limit."""
    bomb = circuits.pack(b'\x00' * (10 * LIMITS.max_file_bytes))
    assert len(bomb) < LIMITS.max_file_bytes
    with pytest.raises(circuits.Rejected) as caught:
        circuits.decompress(bomb, LIMITS)
    assert caught.value.code == 'file_too_large'
    assert circuits.decompress(circuits.pack(b'\x00' * LIMITS.max_file_bytes), LIMITS) == b'\x00' * LIMITS.max_file_bytes


def test_a_rejected_compressed_file_is_identified_by_its_own_hash():
    data = circuits.pack(toy.kmb(toy.GOOD))[:-5]
    receipt = verify.verify(data, toy.PROBLEM, random_shots=256, workers=1)
    assert receipt['failure']['code'] == 'unreadable'
    assert receipt['circuit']['file_sha256'] == hashlib.sha256(data).hexdigest()


# Submissions.


def make(tmp_path, files: dict[str, bytes]):
    directory = tmp_path / 'submissions' / 'toy-adder'
    directory.mkdir(parents=True)
    meta = {'name': 'Toy adder', 'authors': ['someone'], 'kind': 'submission', 'problem': toy.PROBLEM.name,
            'path': 'submissions/toy-adder', 'description': 'A four-bit adder.'}
    (directory / 'meta.json').write_text(json.dumps(meta))
    for name, data in files.items():
        (directory / name).write_bytes(data)
    return directory


@pytest.mark.parametrize('name', ['circuit.kmb.zst', 'circuit.kmx.zst'])
def test_compressed_submission_is_accepted(tmp_path, name):
    raw = toy.kmb(toy.GOOD) if 'kmb' in name else toy.GOOD.encode()
    _, path = submission.check(make(tmp_path, {name: circuits.pack(raw)}), external=True)
    assert path.name == name


def test_large_uncompressed_submission_is_rejected(tmp_path):
    big = toy.GOOD + 'X q0\n' * (submission.MAX_UNCOMPRESSED_BYTES // 5)
    with pytest.raises(submission.Invalid, match='sha-verify pack circuit.kmx --rm'):
        submission.check(make(tmp_path, {'circuit.kmx': big.encode()}))


def test_compressed_and_uncompressed_together_are_rejected(tmp_path):
    raw = toy.kmb(toy.GOOD)
    with pytest.raises(submission.Invalid, match='exactly one of'):
        submission.check(make(tmp_path, {'circuit.kmb': raw, 'circuit.kmb.zst': circuits.pack(raw)}))


def test_pull_request_with_a_compressed_circuit():
    changed = [{'filename': f'submissions/a/{f}', 'status': 'added'} for f in ('circuit.kmb.zst', 'meta.json')]
    assert submission.directory_of_change(changed) == 'a'


# The command line.


def test_pack_command(tmp_path, capsys):
    source = tmp_path / 'circuit.kmb'
    source.write_bytes(toy.kmb(toy.GOOD))
    assert cli.main(['pack', str(source)]) == 0
    target = tmp_path / 'circuit.kmb.zst'
    assert source.exists() and circuits.decompress(target.read_bytes()) == source.read_bytes()

    assert cli.main(['pack', str(source), '--rm']) == 0
    assert not source.exists() and target.exists()

    with pytest.raises(SystemExit, match='already zstd-compressed'):
        cli.main(['pack', str(target)])


def test_run_and_replay_a_compressed_submission(tmp_path, capsys):
    directory = make(tmp_path, {'circuit.kmx.zst': circuits.pack(toy.GOOD.encode())})
    results = tmp_path / 'results'
    circuit = str(directory / 'circuit.kmx.zst')
    assert cli.main(['run', circuit, '--problem', toy.PROBLEM.name, '--shots', '256', '--workers', '1',
                     '--results-dir', str(results)]) == 0
    receipt = str(next((results / toy.PROBLEM.name).glob('*.json')))
    capsys.readouterr()
    assert cli.main(['replay', receipt, str(directory), '--workers', '1']) == 0
    assert capsys.readouterr().out.startswith('MATCH: PASS')
