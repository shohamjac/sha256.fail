import kickmix as km
import pytest

from sha_verifier import cli, selftest


@pytest.mark.parametrize('check', selftest.CHECKS, ids=lambda c: c.__name__)
def test_check_passes(check):
    check()


def test_report_fails_when_a_check_fails(monkeypatch):
    def check_broken():
        raise AssertionError('boom')

    monkeypatch.setattr(selftest, 'CHECKS', (selftest.check_adder_exhaustive, check_broken))
    report = selftest.run()
    assert report['status'] == 'FAIL'
    assert [c['status'] for c in report['checks']] == ['PASS', 'FAIL']
    assert cli.main(['selftest']) == 1


def test_cli_selftest_passes(capsys):
    assert cli.main(['selftest']) == 0
    assert 'selftest: PASS' in capsys.readouterr().out


def test_clean_adder_outcome_is_all_zero():
    outcome = selftest.run_adder(km.Circuit(selftest.ADDER_KMX))
    assert outcome.passed
    assert (outcome.wrong_output, outcome.input_changed, outcome.dirty_scratch,
            outcome.phase_flipped) == (0, 0, 0, 0)
