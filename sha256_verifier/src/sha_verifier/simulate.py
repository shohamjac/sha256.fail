"""Running a circuit on test inputs and checking every shot.

A shot passes when the output registers hold the reference value, the input registers are
unchanged, every scratch qubit is zero and the phase is not flipped.
"""

from __future__ import annotations

import dataclasses
import multiprocessing
import os

import kickmix as km
import numpy as np

from sha_verifier import sampling
from sha_verifier.circuits import Layout
from sha_verifier.problems import TOFFOLI_LIKE, ProblemSpec, RegisterBits

# In the order they are reported when one shot fails several.
CHECKS = ('wrong_output', 'input_changed', 'dirty_scratch', 'phase_flipped')

_MESSAGES = {
    'wrong_output': 'An output register does not hold the reference value.',
    'input_changed': 'An input register was not restored.',
    'dirty_scratch': 'A scratch qubit did not return to zero.',
    'phase_flipped': 'The shot ended with a flipped phase.',
}


@dataclasses.dataclass(frozen=True)
class Failure:
    """The first failing shot of a run.

    Attributes:
        check: Which check failed, one of `CHECKS`.
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

    Returns:
        The number of Toffoli-like instructions executed, summed over the shots run, and
        the first failure if there was one.
    """
    shots = next(iter(inputs.values())).shape[1]
    if shots % sampling.BATCH_SIZE:
        raise ValueError(f'Shot count {shots} is not a multiple of {sampling.BATCH_SIZE}.')
    sim = km.Simulator(batch_size=sampling.BATCH_SIZE, debug_print=False,
                       counting_operations=True, seed=sim_seed)

    for start in range(0, shots, sampling.BATCH_SIZE):
        batch = slice(start, start + sampling.BATCH_SIZE)
        sim.clear_for_shot()  # Zeros every qubit and bit, so outputs and scratch start at zero.
        for register in problem.inputs:
            sim.write_across_shots(layout.registers[register.name], inputs[register.name][:, batch])
        sim.do(circuit)

        bad = {check: np.zeros(sampling.BATCH_SIZE, dtype=bool) for check in CHECKS}
        for register in problem.outputs:
            got = sim.read_across_shots(layout.registers[register.name])
            bad['wrong_output'] |= (got != expected[register.name][:, batch]).any(axis=0)
        for register in problem.inputs:
            got = sim.read_across_shots(layout.registers[register.name])
            bad['input_changed'] |= (got != inputs[register.name][:, batch]).any(axis=0)
        if len(layout.scratch):
            bad['dirty_scratch'] |= sim.read_across_shots(layout.scratch).any(axis=0)
        bad['phase_flipped'] |= np.asarray(sim.read_phase_flipped_across_shots(), dtype=bool)

        any_bad = np.logical_or.reduce(list(bad.values()))
        if any_bad.any():
            first = int(np.argmax(any_bad))
            return _toffolis_executed(sim), Failure(
                check=next(check for check in CHECKS if bad[check][first]),
                shot=start + first,
                failing_shots={check: int(bad[check].sum()) for check in CHECKS},
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
    """
    global _STATE
    tasks = sampling.chunks(shots)
    workers = max(1, min(workers, len(tasks)))
    _STATE = (circuit, layout, problem, seed)
    try:
        total = 0
        if workers == 1 or 'fork' not in multiprocessing.get_all_start_methods():
            results = map(_run_chunk, tasks)
            pool = None
        else:
            pool = multiprocessing.get_context('fork').Pool(workers)
            results = pool.imap(_run_chunk, tasks)
        try:
            for toffolis, failure in results:
                total += toffolis
                if failure is not None:
                    return total, failure
            return total, None
        finally:
            if pool is not None:
                pool.terminate()
                pool.join()
    finally:
        _STATE = None
