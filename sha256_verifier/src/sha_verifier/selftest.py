"""Checks that the simulator stack works and that basic faults are detectable.

This is the milestone-0 self-test: it runs a 4-bit adder on every possible input and a
set of deliberately broken circuits, each of which must be caught. It does not test
SHA-256; the hash problem and its mutation suite arrive with the verifier proper.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
from typing import Callable

import kickmix as km
import numpy as np

from sha_verifier import environment

WIDTH = 4
BATCH = 1 << (2 * WIDTH)  # Every (a, t) pair of 4-bit values is one batch of 256 shots.
SEED = int(hashlib.sha256(b'sha-verifier selftest').hexdigest(), 16)

# `t += a (mod 16)` with measurement-based uncomputation of the two carry qubits, as
# emitted by `km.CircuitBuilder.iadd`. q8 and q9 are scratch.
ADDER_KMX = """
APPEND_TO_REGISTER q0 r0
APPEND_TO_REGISTER q1 r0
APPEND_TO_REGISTER q2 r0
APPEND_TO_REGISTER q3 r0
REGISTER r0 "a"
APPEND_TO_REGISTER q4 r1
APPEND_TO_REGISTER q5 r1
APPEND_TO_REGISTER q6 r1
APPEND_TO_REGISTER q7 r1
REGISTER r1 "t"
CX q3 q7
R q8
CCX q4 q0 q8
CX q8 q1
CX q8 q5
R q9
CCX q1 q5 q9
CX q9 q8
CX q8 q2
CX q8 q6
CX q8 q7
CCX q6 q2 q7
CX q2 q6
CX q8 q6
CX q8 q2
CX q9 q8
HMR q9 b0
CZ q5 q1 if b0
CX q1 q5
CX q8 q5
CX q8 q1
HMR q8 b0
CZ q4 q0 if b0
CX q0 q4
"""


@dataclasses.dataclass(frozen=True)
class Outcome:
    """What one batch of shots of an adder-shaped circuit did."""
    wrong_output: int  # Shots where `t` is not `a + t mod 16`.
    input_changed: int  # Shots where `a` was not restored.
    dirty_scratch: int  # Shots where some non-register qubit ended in |1>.
    phase_flipped: int  # Shots that ended with a -1 phase.
    toffoli_per_shot: float

    @property
    def passed(self) -> bool:
        return not (self.wrong_output or self.input_changed or self.dirty_scratch
                    or self.phase_flipped)


def _to_bits(values: np.ndarray, width: int) -> np.ndarray:
    return ((values[None, :] >> np.arange(width)[:, None]) & 1).astype(bool)


def _from_bits(bits: np.ndarray) -> np.ndarray:
    return (bits.astype(np.int64) << np.arange(len(bits))[:, None]).sum(axis=0)


def canonical_sha256(circuit: km.Circuit) -> str:
    """SHA-256 of the circuit's `.kmb` serialization."""
    buffer = io.BytesIO()
    circuit.to_file(buffer, format='kmb')
    return hashlib.sha256(buffer.getvalue()).hexdigest()


def run_adder(circuit: km.Circuit, *, seed: int = SEED) -> Outcome:
    """Runs `circuit` on all 256 `(a, t)` inputs and checks it as a clean adder."""
    registers = circuit.register_data
    a_reg, t_reg = km.array(list(registers['a'])), km.array(list(registers['t']))
    in_register = set(registers['a']) | set(registers['t'])
    scratch = km.array([km.q(i) for i in range(circuit.num_qubits) if km.q(i) not in in_register])

    shots = np.arange(BATCH)
    a, t = shots & (2**WIDTH - 1), shots >> WIDTH
    sim = km.Simulator(batch_size=BATCH, debug_print=False, counting_operations=True, seed=seed)
    sim.clear_for_shot()
    sim.write_across_shots(a_reg, _to_bits(a, WIDTH))
    sim.write_across_shots(t_reg, _to_bits(t, WIDTH))
    sim.do(circuit)

    dirty = sim.read_across_shots(scratch).any(axis=0) if len(scratch) else np.zeros(BATCH, bool)
    return Outcome(
        wrong_output=int((_from_bits(sim.read_across_shots(t_reg)) != (a + t) % 2**WIDTH).sum()),
        input_changed=int((_from_bits(sim.read_across_shots(a_reg)) != a).sum()),
        dirty_scratch=int(dirty.sum()),
        phase_flipped=int(np.asarray(sim.read_phase_flipped_across_shots()).sum()),
        toffoli_per_shot=sim.operation_statistics().num_toffoli_like / BATCH,
    )


def _mutated(remove: str = '', append: str = '') -> km.Circuit:
    text = ADDER_KMX
    if remove:
        if text.count(remove + '\n') != 1:
            raise AssertionError(f'Mutation target {remove!r} is not a unique line.')
        text = text.replace(remove + '\n', '')
    return km.Circuit(text + append)


# Checks. Each returns a short detail string and raises AssertionError on failure.


def check_kickmix_version() -> str:
    version = environment.kickmix_version()
    assert version == environment.EXPECTED_KICKMIX_VERSION, (
        f'Kickmix {version} is installed, expected {environment.EXPECTED_KICKMIX_VERSION}.')
    return version


def check_adder_exhaustive() -> str:
    circuit = km.Circuit(ADDER_KMX)
    outcome = run_adder(circuit)
    assert outcome.passed, outcome
    assert outcome.toffoli_per_shot == 3.0, outcome
    assert circuit.num_qubits == 10, circuit.num_qubits
    return f'{BATCH} shots, {outcome.toffoli_per_shot:g} Toffolis per shot, {circuit.num_qubits} qubits'


def check_serialization_round_trip() -> str:
    circuit = km.Circuit(ADDER_KMX)
    digest = canonical_sha256(circuit)
    for fmt in ('kmb', 'kmx'):
        buffer = io.BytesIO()
        circuit.to_file(buffer, format=fmt)
        buffer.seek(0)
        assert canonical_sha256(km.Circuit.from_file(buffer, format=fmt)) == digest, fmt
    return digest[:16]


def check_seed_reproducible() -> str:
    """Measurement outcomes depend only on the seed."""
    dirty = _mutated(remove='CZ q5 q1 if b0')
    first, again, other = (run_adder(dirty, seed=s) for s in (SEED, SEED, SEED + 1))
    assert first == again, (first, again)
    assert first.phase_flipped != other.phase_flipped, 'Different seeds gave the same phase flips.'
    return f'{first.phase_flipped} flips with seed A twice, {other.phase_flipped} with seed B'


def check_catches_wrong_output() -> str:
    outcome = run_adder(_mutated(remove='CX q8 q7'))
    assert outcome.wrong_output > 0, outcome
    return f'{outcome.wrong_output} of {BATCH} shots wrong'


def check_catches_changed_input() -> str:
    outcome = run_adder(_mutated(append='X q0\n'))
    assert outcome.input_changed == BATCH, outcome
    return f'{outcome.input_changed} of {BATCH} shots changed'


def check_catches_dirty_scratch() -> str:
    outcome = run_adder(_mutated(append='X q8\n'))
    assert outcome.dirty_scratch == BATCH, outcome
    return f'{outcome.dirty_scratch} of {BATCH} shots dirty'


def check_catches_missing_phase_fixup() -> str:
    outcome = run_adder(_mutated(remove='CZ q5 q1 if b0'))
    assert outcome.phase_flipped > 0 and not outcome.wrong_output, outcome
    return f'{outcome.phase_flipped} of {BATCH} shots phase-flipped'


def check_catches_global_phase() -> str:
    outcome = run_adder(_mutated(append='NEG\n'))
    assert outcome.phase_flipped == BATCH, outcome
    return f'{outcome.phase_flipped} of {BATCH} shots phase-flipped'


def check_sparse_qubit_index_is_counted() -> str:
    circuit = km.Circuit('X q5000')
    assert circuit.num_qubits == 5001, circuit.num_qubits
    return f'X q5000 counts as {circuit.num_qubits} qubits'


def check_rejects_aliased_operands() -> str:
    for text in ('CCX q0 q0 q1', 'CX q0 q0'):
        try:
            km.Circuit(text)
        except Exception:
            continue
        raise AssertionError(f'Kickmix accepted {text!r}.')
    return 'CCX q0 q0 q1 and CX q0 q0 rejected'


def check_rotations_are_visible() -> str:
    """`Z_POW` is not allowed in hash circuits, so the verifier must be able to see it."""
    stats = km.Circuit('Z_POW q0 0.123').operation_statistics()
    assert stats.get('Z_POW') == 1, dict(stats)
    return 'Z_POW shows up in operation statistics'


CHECKS: tuple[Callable[[], str], ...] = (
    check_kickmix_version,
    check_adder_exhaustive,
    check_serialization_round_trip,
    check_seed_reproducible,
    check_catches_wrong_output,
    check_catches_changed_input,
    check_catches_dirty_scratch,
    check_catches_missing_phase_fixup,
    check_catches_global_phase,
    check_sparse_qubit_index_is_counted,
    check_rejects_aliased_operands,
    check_rotations_are_visible,
)


def run() -> dict:
    """Runs every check; returns a report with one entry per check."""
    results = []
    for check in CHECKS:
        name = check.__name__.removeprefix('check_')
        try:
            results.append({'name': name, 'status': 'PASS', 'detail': check()})
        except Exception as ex:  # A crash in a check is a failed check, not a crashed self-test.
            results.append({'name': name, 'status': 'FAIL', 'detail': f'{type(ex).__name__}: {ex}'})
    return {
        'status': 'PASS' if all(r['status'] == 'PASS' for r in results) else 'FAIL',
        'checks': results,
        'environment': environment.describe(),
    }
