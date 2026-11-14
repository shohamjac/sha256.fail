import json

import pytest

import toy
from sha_verifier import cli, problems


@pytest.fixture(autouse=True)
def toy_problem(monkeypatch):
    monkeypatch.setitem(problems.PROBLEMS, toy.PROBLEM.name, toy.PROBLEM)


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def test_run_pass(tmp_path, capsys):
    circuit = write(tmp_path, 'good.kmx', toy.GOOD)
    meta = write(tmp_path, 'meta.json', json.dumps({'name': 'toy', 'authors': ['a']}))
    results = tmp_path / 'results'
    code = cli.main(['run', circuit, '--problem', 'toy-add4-v0', '--salt', 'x', '--workers', '1',
                     '--meta', meta, '--results-dir', str(results)])
    assert code == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt['status'] == 'PASS' and receipt['verification']['salt'] == 'x'
    assert receipt['submission'] == {'name': 'toy', 'authors': ['a']}
    saved = results / 'toy-add4-v0' / f"{receipt['circuit']['sha256']}.json"
    assert json.loads(saved.read_text()) == receipt


def test_run_fail_exits_1(tmp_path, capsys):
    circuit = write(tmp_path, 'bad.kmx', toy.GOOD + 'NEG\n')
    assert cli.main(['run', circuit, '--problem', 'toy-add4-v0', '--workers', '1']) == 1
    assert json.loads(capsys.readouterr().out)['failure']['code'] == 'phase_flipped'


def test_unloadable_file_is_saved_under_its_file_hash(tmp_path, capsys):
    circuit = write(tmp_path, 'junk.kmx', 'NOT A CIRCUIT\n')
    results = tmp_path / 'results'
    assert cli.main(['run', circuit, '--problem', 'toy-add4-v0', '--results-dir', str(results)]) == 1
    receipt = json.loads(capsys.readouterr().out)
    assert (results / 'toy-add4-v0' / f"{receipt['circuit']['file_sha256']}.json").exists()


def test_random_salt_is_recorded_and_fresh(tmp_path, capsys):
    circuit = write(tmp_path, 'good.kmx', toy.GOOD)
    salts = []
    for _ in range(2):
        assert cli.main(['run', circuit, '--problem', 'toy-add4-v0', '--random-salt', '--shots', '256']) == 0
        salts.append(json.loads(capsys.readouterr().out)['verification']['salt'])
    assert len(salts[0]) == 64 and salts[0] != salts[1]


def test_salt_and_random_salt_are_exclusive(tmp_path):
    with pytest.raises(SystemExit):
        cli.main(['run', write(tmp_path, 'g.kmx', toy.GOOD), '--salt', 'x', '--random-salt'])


def test_default_problem_is_sha256(tmp_path, capsys):
    circuit = write(tmp_path, 'nothing.kmx', toy.sha256_do_nothing())
    assert cli.main(['run', circuit, '--shots', '256']) == 1
    assert json.loads(capsys.readouterr().out)['problem'] == 'sha256-compress-v1'


def test_collect(tmp_path, capsys):
    results = tmp_path / 'results'
    for name, text in (('good.kmx', toy.GOOD), ('bad.kmx', toy.GOOD + 'NEG\n')):
        cli.main(['run', write(tmp_path, name, text), '--problem', 'toy-add4-v0', '--shots', '256',
                  '--results-dir', str(results)])
    capsys.readouterr()
    assert cli.main(['collect', str(results)]) == 0
    index = json.loads((results / 'index.json').read_text())
    assert sorted(r['status'] for r in index['receipts']) == ['FAIL', 'PASS']
    # Collecting again does not pick up the index itself.
    assert cli.main(['collect', str(results)]) == 0
    assert len(json.loads((results / 'index.json').read_text())['receipts']) == 2


def test_collect_refuses_files_that_are_not_receipts(tmp_path):
    (tmp_path / 'stray.json').write_text('{"hello": 1}')
    with pytest.raises(SystemExit):
        cli.main(['collect', str(tmp_path)])
