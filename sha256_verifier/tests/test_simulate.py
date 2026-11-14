"""The parallel random-test stage: stopping early and surviving a dead worker.

`multiprocessing.Pool` was used here first. Terminating it after an early failure deadlocked
about once in five thousand runs (a killed worker still held a queue lock), which hung CI.
These tests pin the properties the replacement must keep.
"""

import multiprocessing
import os
import time

import pytest

import toy
from sha_verifier import circuits, sampling, simulate


def prepared(text):
    loaded = circuits.load(text.encode())
    return loaded.circuit, circuits.check_structure(loaded, toy.PROBLEM)


def test_no_worker_processes_are_left_behind():
    for text in (toy.GOOD, toy.RARE_WRONG_OUTPUT):
        circuit, layout = prepared(text)
        simulate.run_random(circuit, layout, toy.PROBLEM, b'\x01' * 32, 4 * 4096, workers=4)
        assert multiprocessing.active_children() == []


def test_many_early_stops_in_a_row():
    """Each run fails in its first chunks while other chunks are queued and in flight."""
    circuit, layout = prepared(toy.RARE_WRONG_OUTPUT)
    started = time.monotonic()
    for i in range(60):
        seed = sampling.derive_seed(toy.PROBLEM, 'ab' * 32, str(i))
        _, failure = simulate.run_random(circuit, layout, toy.PROBLEM, seed, 16 * 4096, workers=2 + i % 4)
        assert failure is not None and failure.check == 'wrong_output'
    assert time.monotonic() - started < 120


def test_early_stop_reports_the_first_failing_chunk_whatever_the_worker_count():
    circuit, layout = prepared(toy.RARE_WRONG_OUTPUT)
    seed = b'\x07' * 32
    results = [simulate.run_random(circuit, layout, toy.PROBLEM, seed, 8 * 4096, workers=w) for w in (1, 2, 3, 8)]
    assert all(r == results[0] for r in results)
    assert results[0][1].shot < 4096


_REAL_RUN_CHUNK = simulate._run_chunk


# Module-level, so that they can be sent to a worker process like the real function.
def _die(task):
    os._exit(1)


def _die_in_chunk_two(task):
    if task[0] == 2:
        os._exit(1)
    return _REAL_RUN_CHUNK(task)


@pytest.mark.parametrize('crash', [_die, _die_in_chunk_two], ids=['every worker', 'one worker mid-run'])
def test_a_dead_worker_is_an_error_not_a_hang(monkeypatch, crash):
    """If the simulator crashes a worker process, the run must fail promptly."""
    monkeypatch.setattr(simulate, '_run_chunk', crash)
    circuit, layout = prepared(toy.GOOD)
    started = time.monotonic()
    with pytest.raises(RuntimeError, match='worker process died'):
        simulate.run_random(circuit, layout, toy.PROBLEM, b'\x02' * 32, 8 * 4096, workers=3)
    assert time.monotonic() - started < 30
    assert multiprocessing.active_children() == []


def test_single_worker_runs_in_process(monkeypatch):
    def no_pool(*args, **kwargs):
        raise AssertionError('a process pool was created for one worker')

    monkeypatch.setattr(simulate.concurrent.futures, 'ProcessPoolExecutor', no_pool)
    circuit, layout = prepared(toy.GOOD)
    total, failure = simulate.run_random(circuit, layout, toy.PROBLEM, b'\x03' * 32, 4096, workers=1)
    assert failure is None and total == toy.TOFFOLIS * 4096


def test_command_line_process_has_one_thread_when_it_forks():
    """Imported the way the command line imports it, the verifier starts no extra threads."""
    import subprocess
    import sys
    script = ("from sha_verifier import cli; import numpy, kickmix, threading; "
              "print(threading.active_count(), open('/proc/self/status').read().split('Threads:')[1].split()[0])")
    out = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, check=True).stdout.split()
    assert out == ['1', '1'], out
