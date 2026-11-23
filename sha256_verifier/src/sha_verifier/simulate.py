"""Running a circuit on test inputs and checking every shot.

A shot passes when the output registers hold the reference value, the input registers made
of qubits are unchanged, every scratch qubit is zero and the phase is right: not flipped,
or for a problem that defines a phase, flipped exactly when the problem says so.
"""

from __future__ import annotations

import concurrent.futures
import concurrent.futures.process
import dataclasses
import multiprocessing
import os

import kickmix as km
import numpy as np

from sha_verifier import sampling
from sha_verifier.circuits import Layout
from sha_verifier.problems import TOFFOLI_LIKE, ProblemSpec, RegisterBits

# In the order they are reported when one shot fails several. The last check is
# `phase_flipped` for a problem with no phase of its own and `wrong_phase` for one with.
CHECKS = ('wrong_output', 'input_changed', 'dirty_scratch', 'phase_flipped')
PHASE_ORACLE_CHECKS = CHECKS[:3] + ('wrong_phase',)

_MESSAGES = {
    'wrong_output': 'An output register does not hold the reference value.',
    'input_changed': 'An input register was not restored.',
    'dirty_scratch': 'A scratch qubit did not return to zero.',
    'phase_flipped': 'The shot ended with a flipped phase.',
    'wrong_phase': 'The phase was flipped when it must not be, or not flipped when it must be.',
}


def checks(problem: ProblemSpec) -> tuple[str, ...]:
    """The checks every shot of `problem` goes through, in reporting order."""
    return CHECKS if problem.phase is None else PHASE_ORACLE_CHECKS


@dataclasses.dataclass(frozen=True)
class Failure:
    """The first failing shot of a run.

    Attributes:
        check: Which check failed, one of the problem's `checks`.
        shot: Index of the shot within its phase (directed or random).
        failing_shots: For each check, how many shots of the same batch failed it.
        inputs: The failing shot's input registers, as hex of the register bits packed
            eight per byte with offset 0 in the least significant bit of the first byte.
    """
    check: str
    shot: int
    failing_shots: dict[str, int]
    inputs: dict[str, str]

    @property
    def message(self) -> str:
        return _MESSAGES[self.check]


def _toffolis_executed(sim: km.Simulator) -> int:
    stats = sim.operation_statistics()
    return int(sum(stats.get(name, 0) for name in TOFFOLI_LIKE))


def run_shots(circuit: km.Circuit, layout: Layout, problem: ProblemSpec, inputs: RegisterBits,
              expected: RegisterBits, sim_seed: int) -> tuple[int, Failure | None]:
    """Simulates one shot per input column, in batches, stopping at the first failing batch.

    The expected phase of each shot comes from `problem.phase`, when the problem has one.

    Returns:
        The number of Toffoli-like instructions executed, summed over the shots run, and
        the first failure if there was one.
    """
    shots = next(iter(inputs.values())).shape[1]
    if shots % sampling.BATCH_SIZE:
        raise ValueError(f'Shot count {shots} is not a multiple of {sampling.BATCH_SIZE}.')
    sim = km.Simulator(batch_size=sampling.BATCH_SIZE, debug_print=False,
                       counting_operations=True, seed=sim_seed)
    names = checks(problem)
    must_flip = None if problem.phase is None else np.asarray(problem.phase(inputs), dtype=bool)

    for start in range(0, shots, sampling.BATCH_SIZE):
        batch = slice(start, start + sampling.BATCH_SIZE)
        sim.clear_for_shot()  # Zeros every qubit and bit, so outputs and scratch start at zero.
        for register in problem.inputs:
            sim.write_across_shots(layout.registers[register.name], inputs[register.name][:, batch])
        sim.do(circuit)

        bad = {check: np.zeros(sampling.BATCH_SIZE, dtype=bool) for check in names}
        for register in problem.outputs:
            got = sim.read_across_shots(layout.registers[register.name])
            bad['wrong_output'] |= (got != expected[register.name][:, batch]).any(axis=0)
        for register in problem.inputs:
            if register.kind == 'qubit':  # Classical bits may end in any state.
                got = sim.read_across_shots(layout.registers[register.name])
                bad['input_changed'] |= (got != inputs[register.name][:, batch]).any(axis=0)
        if len(layout.scratch):
            bad['dirty_scratch'] |= sim.read_across_shots(layout.scratch).any(axis=0)
        flipped = np.asarray(sim.read_phase_flipped_across_shots(), dtype=bool)
        if must_flip is None:
            bad['phase_flipped'] |= flipped
        else:
            bad['wrong_phase'] |= flipped != must_flip[batch]

        any_bad = np.logical_or.reduce(list(bad.values()))
        if any_bad.any():
            first = int(np.argmax(any_bad))
            return _toffolis_executed(sim), Failure(
                check=next(check for check in names if bad[check][first]),
                shot=start + first,
                failing_shots={check: int(bad[check].sum()) for check in names},
                inputs={r.name: np.packbits(inputs[r.name][:, start + first], bitorder='little').tobytes().hex()
                        for r in problem.inputs},
            )
    return _toffolis_executed(sim), None


def run_directed(circuit: km.Circuit, layout: Layout, problem: ProblemSpec, seed: bytes
                 ) -> tuple[int, Failure | None]:
    """Runs the problem's directed tests. Returns how many there are and the first failure."""
    inputs = problem.directed_inputs()
    count = next(iter(inputs.values())).shape[1]
    # Fill the last batch by repeating earlier tests; the repeats are checked like the rest.
    filler = np.arange(-(-count // sampling.BATCH_SIZE) * sampling.BATCH_SIZE) % count
    padded = {name: bits[:, filler] for name, bits in inputs.items()}
    _, failure = run_shots(circuit, layout, problem, padded, problem.reference(padded),
                           sampling.simulator_seed(seed, 'directed', 0))
    if failure is not None:
        failure = dataclasses.replace(failure, shot=failure.shot % count)
    return count, failure


# Random shots run in worker processes. Workers are forked, so they inherit this state
# instead of receiving it through a pipe.
_STATE: tuple[km.Circuit, Layout, ProblemSpec, bytes] | None = None


def _run_chunk(task: tuple[int, int]) -> tuple[int, Failure | None]:
    chunk, shots = task
    circuit, layout, problem, seed = _STATE
    inputs = sampling.random_inputs(problem, seed, chunk, shots)
    toffolis, failure = run_shots(circuit, layout, problem, inputs, problem.reference(inputs),
                                  sampling.simulator_seed(seed, 'random', chunk))
    if failure is not None:
        failure = dataclasses.replace(failure, shot=chunk * sampling.CHUNK_SHOTS + failure.shot)
    return toffolis, failure


def available_workers() -> int:
    return len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else (os.cpu_count() or 1)


def run_random(circuit: km.Circuit, layout: Layout, problem: ProblemSpec, seed: bytes, shots: int,
               workers: int) -> tuple[int, Failure | None]:
    """Runs `shots` random shots across `workers` processes.

    Chunks are consumed in order and the run stops at the first failing one, so the result
    does not depend on the number of workers.

    Returns:
        The number of Toffoli-like instructions executed over all shots (meaningful only
        when there is no failure), and the first failure if there was one.

    Raises:
        RuntimeError: A worker process died, which means the simulator crashed.
    """
    global _STATE
    tasks = sampling.chunks(shots)
    workers = max(1, min(workers, len(tasks)))
    _STATE = (circuit, layout, problem, seed)
    try:
        if workers == 1 or 'fork' not in multiprocessing.get_all_start_methods():
            return _first_failure(map(_run_chunk, tasks))

        # Not multiprocessing.Pool: stopping one early means terminate(), which kills workers
        # mid-task and can deadlock on a queue lock a dead worker still holds; and a Pool
        # waits forever on a worker that crashes. This executor reports a dead worker, and
        # on an early stop it is shut down without killing anything: chunks not yet started
        # are dropped and the few in flight are left to finish.
        pool = concurrent.futures.ProcessPoolExecutor(max_workers=workers,
                                                      mp_context=multiprocessing.get_context('fork'))
        try:
            futures = [pool.submit(_run_chunk, task) for task in tasks]
            return _first_failure(future.result() for future in futures)
        except concurrent.futures.process.BrokenProcessPool:
            raise RuntimeError('A simulator worker process died while running the circuit.') from None
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
    finally:
        _STATE = None


def _first_failure(results) -> tuple[int, Failure | None]:
    """Sums executed Toffolis over chunk results, in order, up to and including the first failure."""
    total = 0
    for toffolis, failure in results:
        total += toffolis
        if failure is not None:
            return total, failure
    return total, None
