"""Verifying a submitted circuit against a problem and producing its receipt.

`verify` is the whole verifier as one function: bytes in, receipt out. The command line,
CI, and any future service are wrappers around it.

A receipt is a JSON-compatible dict, described by `schema/receipt.schema.json`. Everything
in it except the `run` section is a function of the circuit, the problem, the salt and the
number of random shots, so re-running with the same four reproduces it exactly.
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import platform
import time

import numpy as np

from sha_verifier import __version__, circuits, environment, sampling, simulate
from sha_verifier.problems import TOFFOLI_LIKE, ProblemSpec

RECEIPT_VERSION = 1


def _failure(stage: str, code: str, message: str, shot: simulate.Failure | None = None) -> dict:
    return {
        'stage': stage,
        'code': code,
        'message': message,
        'shot': shot.shot if shot else None,
        'inputs': shot.inputs if shot else None,
        'failing_shots': shot.failing_shots if shot else None,
    }


def verify(data: bytes, problem: ProblemSpec, *, salt: str = '', random_shots: int | None = None,
           workers: int | None = None, submission: dict | None = None) -> dict:
    """Verifies a circuit file against `problem`.

    A circuit that fails any check gives a receipt with status `FAIL`; this function raises
    only for a mistake by the caller.

    Args:
        data: The contents of a `.kmb` or `.kmx` file.
        salt: Mixed into the seed that selects the random tests. Use an unpredictable salt
            chosen after the circuit is fixed when the result must be trusted by others.
        random_shots: Number of random inputs. Defaults to the problem's full-strength
            count; fewer is for development and is marked as such in the receipt.
        workers: Worker processes for the random shots. Defaults to all available cores.
            Does not affect the result.
        submission: Metadata to carry in the receipt unchanged.
    """
    if random_shots is None:
        random_shots = problem.random_shots
    sampling.chunks(random_shots)  # Validates the count.
    if workers is None:
        workers = simulate.available_workers()
    if workers < 1:
        raise ValueError(f'workers must be at least 1, got {workers}.')

    started = datetime.datetime.now(datetime.timezone.utc)
    clock = time.monotonic()
    loaded = None
    seed = None
    directed_count = None
    failure = None
    cost = None

    try:
        loaded = circuits.load(data)
        layout = circuits.check_structure(loaded, problem)
        seed = sampling.derive_seed(problem, loaded.sha256, salt)

        directed_count, bad_shot = simulate.run_directed(loaded.circuit, layout, problem, seed)
        if bad_shot is not None:
            raise _ShotFailed('directed', bad_shot)

        executed, bad_shot = simulate.run_random(loaded.circuit, layout, problem, seed, random_shots, workers)
        if bad_shot is not None:
            raise _ShotFailed('random', bad_shot)

        # Each Toffoli-like instruction runs at most once per shot, and exactly once unless
        # it is under a classical condition. Anything else means the counts cannot be trusted.
        static = loaded.toffoli_static
        conditional = loaded.summary.conditional_total(TOFFOLI_LIKE)
        if not (static - conditional) * random_shots <= executed <= static * random_shots:
            raise circuits.Rejected(
                'accounting', 'toffoli_count_inconsistent',
                f'{executed} Toffolis executed over {random_shots} shots is impossible for a circuit '
                f'with {static} Toffoli instructions, {conditional} of them conditional.')

        toffoli = executed / random_shots
        cost = {
            'qubits': loaded.summary.num_qubits,
            'toffoli': toffoli,
            'score': loaded.summary.num_qubits * toffoli,
            'toffoli_executed_total': executed,
            'shots': random_shots,
        }
    except circuits.Rejected as ex:
        failure = _failure(ex.stage, ex.code, ex.message)
    except _ShotFailed as ex:
        failure = _failure(ex.stage, ex.shot.check, ex.shot.message, ex.shot)

    return {
        'receipt_version': RECEIPT_VERSION,
        'problem': problem.name,
        'status': 'PASS' if failure is None else 'FAIL',
        'failure': failure,
        'circuit': {
            'file_sha256': hashlib.sha256(data).hexdigest(),
            'sha256': loaded.sha256 if loaded else None,
            'qubits': loaded.summary.num_qubits if loaded else None,
            'bits': loaded.summary.num_bits if loaded else None,
            'operations': loaded.summary.num_operations if loaded else None,
            'toffoli_static': loaded.toffoli_static if loaded else None,
            'instruction_counts': dict(sorted(loaded.summary.counts.items())) if loaded else None,
            'reaction_depth': loaded.circuit.reaction_depth() if loaded else None,
        },
        'cost': cost,
        'verification': {
            'sampling': sampling.SCHEME,
            'salt': salt,
            'seed': seed.hex() if seed else None,
            'directed_shots': directed_count,
            'random_shots': random_shots,
            'full_strength': random_shots >= problem.random_shots,
            'batch_size': sampling.BATCH_SIZE,
            'chunk_shots': sampling.CHUNK_SHOTS,
            'limits': dataclasses.asdict(circuits.LIMITS),
        },
        'verifier': {
            'sha_verifier_version': __version__,
            'kickmix_version': environment.kickmix_version(),
        },
        'submission': submission,
        'run': {
            'started_at': started.isoformat(timespec='seconds'),
            'elapsed_seconds': round(time.monotonic() - clock, 3),
            'workers': workers,
            'kickmix_binary_sha256': environment.kickmix_binary_sha256(),
            'python_version': platform.python_version(),
            'numpy_version': np.__version__,
            'platform': platform.platform(),
            'machine': platform.machine(),
        },
    }


class _ShotFailed(Exception):
    def __init__(self, stage: str, shot: simulate.Failure):
        super().__init__(shot.message)
        self.stage, self.shot = stage, shot


def reproducible_part(receipt: dict) -> dict:
    """The receipt without its `run` section: what a replay must reproduce exactly."""
    return {key: value for key, value in receipt.items() if key != 'run'}
