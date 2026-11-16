"""Checking submissions as they arrive in pull requests, recording receipts, and comments."""

import json

import pytest

import toy
from sha_verifier import cli, problems, submission

GOOD_META = {
    'name': 'Toy adder', 'authors': ['someone'], 'kind': 'submission', 'problem': 'toy-add4-v0',
    'path': 'submissions/toy-adder', 'description': 'A four-bit adder.',
}


@pytest.fixture(autouse=True)
def toy_problem(monkeypatch):
    monkeypatch.setitem(problems.PROBLEMS, toy.PROBLEM.name, toy.PROBLEM)


def added(*paths):
    return [{'filename': p, 'status': 'added'} for p in paths]


def make(tmp_path, name='toy-adder', circuit=toy.GOOD, meta=GOOD_META, circuit_name='circuit.kmx', **overrides):
    directory = tmp_path / 'submissions' / name
    directory.mkdir(parents=True)
    if circuit is not None:
        (directory / circuit_name).write_text(circuit)
    if meta is not None:
        (directory / 'meta.json').write_text(json.dumps({**meta, 'path': f'submissions/{name}', **overrides}))
    return directory


# Which directory a pull request adds.


def test_directory_of_a_well_formed_pull_request():
    changed = added('submissions/my-circuit/circuit.kmb', 'submissions/my-circuit/meta.json',
                    'submissions/my-circuit/build.py', 'submissions/my-circuit/notes/README.md')
    assert submission.directory_of_change(changed) == 'my-circuit'


def test_pull_request_that_is_not_a_submission():
    with pytest.raises(submission.NotASubmission):
        submission.directory_of_change(added('sha256_verifier/README.md', 'PLAN.md'))


@pytest.mark.parametrize('changed,fragment', [
    (added('submissions/a/circuit.kmb', 'submissions/a/meta.json', 'sha256_verifier/src/sha_verifier/verify.py'),
     'also touches'),
    (added('submissions/a/circuit.kmb', 'submissions/a/meta.json', '.github/workflows/x.yml'), 'also touches'),
    (added('submissions/a/circuit.kmb', 'submissions/a/meta.json', 'submissions/b/meta.json'), 'one submission directory'),
    (added('submissions/circuit.kmb'), 'not inside a submission directory'),
    (added('submissions/Bad_Name/circuit.kmb', 'submissions/Bad_Name/meta.json'), 'directory name'),
    (added('submissions/-a/circuit.kmb', 'submissions/-a/meta.json'), 'directory name'),
    (added('submissions/a/meta.json'), 'exactly one of'),
    (added('submissions/a/circuit.kmb', 'submissions/a/circuit.kmx', 'submissions/a/meta.json'), 'exactly one of'),
    (added('submissions/a/circuit.kmb'), 'must contain `meta.json`'),
    (added('submissions/a/sub/circuit.kmb', 'submissions/a/meta.json'), 'exactly one of'),
    ([{'filename': 'submissions/example/circuit.kmb', 'status': 'modified'},
      {'filename': 'submissions/example/meta.json', 'status': 'added'}], 'only add a new directory'),
    ([{'filename': 'submissions/example/circuit.kmb', 'status': 'removed'}], 'only add a new directory'),
    ([{'filename': 'submissions/a/circuit.kmb', 'status': 'renamed'},
      {'filename': 'submissions/a/meta.json', 'status': 'added'}], 'only add a new directory'),
])
def test_malformed_pull_requests(changed, fragment):
    with pytest.raises(submission.Invalid, match=fragment):
        submission.directory_of_change(changed)


def test_path_names_in_messages_are_sanitized():
    hostile = 'README<img src=x onerror=alert(1)>[x](http://evil).md'
    with pytest.raises(submission.Invalid) as caught:
        submission.directory_of_change(added('submissions/a/circuit.kmb', 'submissions/a/meta.json', hostile))
    message = str(caught.value)
    assert '`READMEimg srcx onerroralert(1)x(http://evil).md`' in message  # Stripped, and inside a code span.
    for forbidden in ('<img', 'onerror=', '](', '[x]'):
        assert forbidden not in message


# meta.json.


def test_good_meta(tmp_path):
    directory = make(tmp_path)
    meta, circuit = submission.check(directory, external=True)
    assert meta == GOOD_META and circuit.name == 'circuit.kmx'


def test_optional_fields(tmp_path):
    directory = make(tmp_path, source='build.py', reference='https://example.org/paper', links=['https://example.org'],
                     github_user_id=1234567)
    meta = submission.load_meta(directory, external=True)
    assert meta['links'] == ['https://example.org'] and meta['github_user_id'] == 1234567


@pytest.mark.parametrize('overrides,fragment', [
    ({'name': ''}, '`name`'),
    ({'name': 'x' * 81}, '`name`'),
    ({'name': 'two\nlines'}, 'control characters'),
    ({'name': 5}, '`name`'),
    ({'authors': 'someone'}, '`authors`'),
    ({'authors': []}, '`authors`'),
    ({'authors': ['a'] * 21}, '`authors`'),
    ({'authors': [3]}, '`authors`'),
    ({'problem': 'sha1'}, '`problem` must be one of'),
    ({'kind': 'winner'}, '`kind` must be one of'),
    ({'kind': 'baseline'}, 'assigned by the maintainers'),
    ({'kind': 'literature'}, 'assigned by the maintainers'),
    ({'group': 'mine'}, '`group` is assigned'),
    ({'path': 'submissions/elsewhere'}, '`path` must be'),
    ({'surprise': 1}, 'not recognised'),
    ({'description': 'x' * 1501}, '`description`'),
    ({'links': ['x'] * 11}, '`links`'),
    ({'github_user_id': 'someone'}, 'not your username'),
    ({'github_user_id': '1234567'}, '`github_user_id`'),
    ({'github_user_id': 0}, '`github_user_id`'),
    ({'github_user_id': -5}, '`github_user_id`'),
    ({'github_user_id': 1.5}, '`github_user_id`'),
    ({'github_user_id': True}, '`github_user_id`'),
    ({'github_user_id': None}, '`github_user_id`'),
    ({'github_user_id': 2**53}, '`github_user_id`'),
])
def test_bad_meta(tmp_path, overrides, fragment):
    directory = make(tmp_path)
    (directory / 'meta.json').write_text(json.dumps({**GOOD_META, **overrides}))
    with pytest.raises(submission.Invalid, match=fragment):
        submission.load_meta(directory, external=True)


@pytest.mark.parametrize('field', ['name', 'authors', 'kind', 'problem', 'path', 'description'])
def test_required_fields(tmp_path, field):
    directory = make(tmp_path)
    (directory / 'meta.json').write_text(json.dumps({k: v for k, v in GOOD_META.items() if k != field}))
    with pytest.raises(submission.Invalid, match=f'`{field}`'):
        submission.load_meta(directory, external=True)


@pytest.mark.parametrize('content,fragment', [
    (b'{not json', 'not valid JSON'), (b'\xff\xfe', 'not valid JSON'), (b'[1, 2]', 'JSON object'),
    (b'{"name": "' + b'x' * 20000 + b'"}', 'the limit is'),
])
def test_unreadable_meta(tmp_path, content, fragment):
    directory = make(tmp_path)
    (directory / 'meta.json').write_bytes(content)
    with pytest.raises(submission.Invalid, match=fragment):
        submission.load_meta(directory)


def test_maintainer_kinds_are_allowed_internally(tmp_path):
    directory = make(tmp_path, kind='literature', group='some-paper')
    assert submission.load_meta(directory)['group'] == 'some-paper'


def test_missing_files(tmp_path):
    with pytest.raises(submission.Invalid, match='meta.json'):
        submission.check(make(tmp_path, name='a', meta=None))
    with pytest.raises(submission.Invalid, match='exactly one of'):
        submission.check(make(tmp_path, name='b', circuit=None))


# Recording receipts on the main branch.


def test_record_verifies_what_is_missing_and_nothing_else(tmp_path):
    make(tmp_path, name='good')
    make(tmp_path, name='broken', circuit=toy.GOOD + 'NEG\n')
    make(tmp_path, name='junk', circuit='NOT A CIRCUIT\n')
    make(tmp_path, name='bad-meta', kind='nonsense')
    subs, results = tmp_path / 'submissions', tmp_path / 'results'

    first = {o['name']: o for o in submission.record(subs, results, workers=1)}
    assert {name: o['outcome'] for name, o in first.items()} == {
        'good': 'PASS', 'broken': 'FAIL', 'junk': 'FAIL', 'bad-meta': 'invalid'}
    assert '`kind`' in first['bad-meta']['message']
    receipts = [json.loads(p.read_text()) for p in (results / 'toy-add4-v0').glob('*.json')]
    assert sorted(r['status'] for r in receipts) == ['FAIL', 'FAIL', 'PASS']
    passed = next(r for r in receipts if r['status'] == 'PASS')
    assert passed['verification']['full_strength'] and len(passed['verification']['salt']) == 64
    assert passed['submission']['path'] == 'submissions/good'

    again = {o['name']: o['outcome'] for o in submission.record(subs, results, workers=1)}
    assert again['good'] == 'current' and again['broken'] == 'current'
    assert again['junk'] == 'FAIL'  # A file that does not load has no circuit hash to match on.


def test_record_reverifies_when_metadata_changes(tmp_path):
    directory = make(tmp_path, name='good')
    subs, results = tmp_path / 'submissions', tmp_path / 'results'
    submission.record(subs, results, workers=1)
    (directory / 'meta.json').write_text(json.dumps({**GOOD_META, 'path': 'submissions/good', 'name': 'Renamed'}))
    assert [o['outcome'] for o in submission.record(subs, results, workers=1)] == ['PASS']
    receipts = list((results / 'toy-add4-v0').glob('*.json'))
    assert len(receipts) == 1 and json.loads(receipts[0].read_text())['submission']['name'] == 'Renamed'


def test_record_never_runs_submission_code(tmp_path):
    directory = make(tmp_path, name='good')
    (directory / 'build.py').write_text('raise SystemExit("submission code was executed")\n')
    (directory / 'conftest.py').write_text('raise SystemExit("submission code was executed")\n')
    assert [o['outcome'] for o in submission.record(tmp_path / 'submissions', tmp_path / 'results', workers=1)] == ['PASS']


# Comments.


def passing(qubits, toffoli, sha='a', depth=None):
    return {
        'problem': 'toy-add4-v0', 'status': 'PASS', 'failure': None,
        'circuit': {'sha256': sha * 64, 'file_sha256': sha * 64, 'reaction_depth': depth},
        'cost': {'qubits': qubits, 'toffoli': toffoli, 'score': qubits * toffoli},
        'verification': {'directed_shots': 5, 'random_shots': 4096, 'full_strength': True, 'salt': 'ab' * 32},
        'submission': {'name': 'x'},
    }


def test_summary_of_a_new_best():
    text = submission.summarize(passing(10, 90, 'n'), [passing(10, 100, 'a'), passing(20, 50, 'b')])
    assert text.startswith(submission.COMMENT_MARKER)
    assert 'Verification passed' in text and '| 10 | 90 | 900 |' in text
    assert 'On the Pareto front' in text and 'dominates 1 verified circuit.' in text
    assert 'New best score' in text and '10.0% below the current best of 1,000' in text


def test_summary_of_a_dominated_circuit():
    text = submission.summarize(passing(30, 200, 'n'), [passing(10, 100, 'a'), passing(20, 50, 'b')])
    assert 'Dominated** by 2 verified circuits' in text
    assert 'New best score' not in text and 'current best score is 1,000' in text


def test_summary_of_a_trade_off_that_is_not_the_best_score():
    text = submission.summarize(passing(5, 400, 'n'), [passing(10, 100, 'a')])
    assert 'On the Pareto front' in text and 'dominates' not in text and 'New best score' not in text


def test_summary_ranks_each_track_on_its_own():
    # Best on reaction depth, dominated on Toffolis.
    text = submission.summarize(passing(10, 200, 'n', depth=5), [passing(10, 100, 'a', depth=20), passing(20, 50, 'b')])
    assert '| Toffoli count | 10 | 200 | 2,000 |' in text and '| Reaction depth | 10 | 5 | 50 |' in text
    toffoli, depth = text.split('**Toffoli count.**')[1].split('**Reaction depth.**')
    assert 'Dominated** by 1 verified circuit:' in toffoli and 'no more Toffolis' in toffoli
    assert 'On the Pareto front' in depth and 'no more reaction depth' in depth and 'dominates 1 verified circuit.' in depth
    assert '**New best score**, 75.0% below the current best of 200.' in depth  # 'b' has no depth, so is left out.


def test_summary_without_a_reaction_depth_shows_only_the_toffoli_track():
    text = submission.summarize(passing(10, 100), [])
    assert '**Toffoli count.**' in text and 'Reaction depth' not in text


def test_summary_of_the_first_circuit_and_of_a_resubmission():
    assert 'first verified circuit' in submission.summarize(passing(10, 100), [])
    same = passing(10, 100, 'a')
    assert 'first verified circuit' in submission.summarize(same, [same])  # Not compared with itself.


def test_summary_ignores_failed_and_reduced_runs():
    failed = {**passing(1, 1, 'f'), 'status': 'FAIL', 'cost': None}
    reduced = passing(1, 1, 'r')
    reduced['verification'] = {**reduced['verification'], 'full_strength': False}
    assert 'first verified circuit' in submission.summarize(passing(10, 100, 'n'), [failed, reduced])


def test_summary_flags_a_reduced_run():
    receipt = passing(10, 100)
    receipt['verification']['full_strength'] = False
    assert 'reduced run' in submission.summarize(receipt, [])


def test_summary_of_a_failure_carries_no_untrusted_markup():
    receipt = {
        'problem': 'toy-add4-v0', 'status': 'FAIL', 'cost': None, 'circuit': {'sha256': None},
        'failure': {'stage': 'load', 'code': 'unreadable', 'shot': None, 'inputs': None, 'failing_shots': None,
                    'message': "Kickmix could not parse: '<script>alert(1)</script> ![x](http://evil) @someone `x`'"},
    }
    text = submission.summarize(receipt, [])
    assert 'Verification failed' in text and '`unreadable`' in text
    body = text.replace(submission.COMMENT_MARKER, '')
    for forbidden in ('<', '>', '[', ']', '!', '@'):
        assert forbidden not in body


def test_summary_of_a_failing_shot():
    receipt = {
        'problem': 'toy-add4-v0', 'status': 'FAIL', 'cost': None, 'circuit': {'sha256': 'a' * 64},
        'failure': {'stage': 'random', 'code': 'wrong_output', 'shot': 17, 'message': 'An output register is wrong.',
                    'inputs': {'a': '0f', 'b': '07'}, 'failing_shots': {'wrong_output': 2}},
    }
    text = submission.summarize(receipt, [])
    assert 'number 17 of the random tests' in text and 'Input `a` of that test (register bits, hex): `0f`' in text


# The commands CI calls.


def test_pr_check_command(tmp_path, capsys):
    changed, comment = tmp_path / 'changed.json', tmp_path / 'comment.md'
    changed.write_text(json.dumps(added('submissions/my-circuit/circuit.kmb', 'submissions/my-circuit/meta.json')))
    assert cli.main(['pr-check', str(changed), '--comment', str(comment)]) == 0
    assert capsys.readouterr().out.strip() == 'my-circuit' and not comment.exists()

    changed.write_text(json.dumps(added('PLAN.md')))
    assert cli.main(['pr-check', str(changed), '--comment', str(comment)]) == 3
    assert not comment.exists()

    changed.write_text(json.dumps(added('submissions/a/meta.json', 'README.md')))
    assert cli.main(['pr-check', str(changed), '--comment', str(comment)]) == 1
    assert 'Submission not verified' in comment.read_text() and 'also touches' in comment.read_text()


def test_pr_verify_command(tmp_path):
    directory = make(tmp_path)
    receipt, comment = tmp_path / 'receipt.json', tmp_path / 'comment.md'
    code = cli.main(['pr-verify', str(directory), '--receipt', str(receipt), '--comment', str(comment), '--workers', '1'])
    assert code == 0
    assert json.loads(receipt.read_text())['status'] == 'PASS'
    assert 'Verification passed' in comment.read_text() and 'first verified circuit' in comment.read_text()


def test_pr_verify_command_on_a_failing_circuit(tmp_path):
    directory = make(tmp_path, circuit=toy.RARE_WRONG_OUTPUT)
    receipt, comment = tmp_path / 'receipt.json', tmp_path / 'comment.md'
    code = cli.main(['pr-verify', str(directory), '--receipt', str(receipt), '--comment', str(comment), '--workers', '1'])
    assert code == 1
    assert json.loads(receipt.read_text())['failure']['stage'] == 'random'
    assert 'Verification failed' in comment.read_text() and '`wrong_output`' in comment.read_text()


def test_pr_verify_command_rejects_maintainer_only_metadata(tmp_path):
    directory = make(tmp_path, kind='baseline')
    receipt, comment = tmp_path / 'receipt.json', tmp_path / 'comment.md'
    assert cli.main(['pr-verify', str(directory), '--receipt', str(receipt), '--comment', str(comment)]) == 1
    assert not receipt.exists() and 'assigned by the maintainers' in comment.read_text()


def pr_verify(directory, tmp_path, *extra):
    receipt, comment = tmp_path / 'receipt.json', tmp_path / 'comment.md'
    code = cli.main(['pr-verify', str(directory), '--receipt', str(receipt), '--comment', str(comment),
                     '--workers', '1', *extra])
    return code, receipt, comment.read_text()


def test_pr_verify_accepts_the_openers_own_github_user_id(tmp_path):
    code, receipt, comment = pr_verify(make(tmp_path, github_user_id=42), tmp_path, '--github-user-id', '42')
    assert code == 0
    assert json.loads(receipt.read_text())['submission']['github_user_id'] == 42
    assert 'anonymous' not in comment


def test_pr_verify_rejects_someone_elses_github_user_id(tmp_path):
    code, receipt, comment = pr_verify(make(tmp_path, github_user_id=43), tmp_path, '--github-user-id', '42')
    assert code == 1 and not receipt.exists()
    assert 'opened by GitHub user ID 42' in comment


def test_pr_verify_tells_an_anonymous_submitter_their_github_user_id(tmp_path):
    code, _, comment = pr_verify(make(tmp_path), tmp_path, '--github-user-id', '42')
    assert code == 0 and '`"github_user_id": 42`' in comment


def test_pr_verify_without_an_opener_skips_the_github_check(tmp_path):
    code, _, comment = pr_verify(make(tmp_path, github_user_id=43), tmp_path)
    assert code == 0 and 'anonymous' not in comment


def test_record_and_check_commands(tmp_path, capsys):
    directory = make(tmp_path, name='good')
    assert cli.main(['check-submission', str(directory), '--external']) == 0
    results = tmp_path / 'results'
    assert cli.main(['record', str(tmp_path / 'submissions'), str(results), '--workers', '1']) == 0
    assert 'PASS     good' in capsys.readouterr().out
    index = json.loads((results / 'index.json').read_text())['receipts']
    assert [r['status'] for r in index] == ['PASS']

    make(tmp_path, name='bad', kind='nonsense')
    assert cli.main(['record', str(tmp_path / 'submissions'), str(results), '--workers', '1']) == 1
    assert cli.main(['check-submission', str(tmp_path / 'submissions' / 'bad')]) == 1
