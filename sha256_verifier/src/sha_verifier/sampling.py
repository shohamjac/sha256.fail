"""Seeds and random test inputs (sampling scheme `v1`).

Everything random in a verification run is derived from one 32-byte seed:

    seed = SHA-256("sha-verifier/seed/v1" 00 problem 00 circuit_sha256 00 salt)

so the tests depend on the circuit (a submitter cannot choose a circuit knowing its tests)
and, through the salt, on something the submitter does not control. Given the seed, the
inputs and the simulator's measurement outcomes are fixed, which makes a run replayable.

Random shots are processed in chunks of `CHUNK_SHOTS`. Chunk `c` holds shots
`c * CHUNK_SHOTS` onward; its inputs are the output of SHAKE-256 over
`seed "inputs" c`, and its simulator seed is SHA-256 over `seed "sim" "random" c`.
Only standard-library hashes are involved, so the stream does not depend on numpy.
"""

from __future__ import annotations

import hashlib

import numpy as np

from sha_verifier.problems import ProblemSpec, RegisterBits

SCHEME = 'v1'
BATCH_SIZE = 256  # Shots simulated together.
CHUNK_SHOTS = 4096  # Shots per unit of work; a multiple of BATCH_SIZE.


def derive_seed(problem: ProblemSpec, circuit_sha256: str, salt: str) -> bytes:
    parts = (b'sha-verifier/seed/v1', problem.name.encode(), circuit_sha256.encode(), salt.encode())
    return hashlib.sha256(b'\x00'.join(parts)).digest()


def simulator_seed(seed: bytes, phase: str, chunk: int) -> int:
    """The 256-bit seed for Kickmix's measurement outcomes in one chunk of one phase."""
    digest = hashlib.sha256(seed + b'sim' + phase.encode() + chunk.to_bytes(8, 'little')).digest()
    return int.from_bytes(digest, 'big')


def random_inputs(problem: ProblemSpec, seed: bytes, chunk: int, shots: int) -> RegisterBits:
    """Random values for the input registers of `shots` shots of chunk `chunk`.

    For a problem with no `random_inputs` of its own they are uniformly random: each shot
    takes `ceil(total_input_bits / 8)` bytes of the chunk's stream, and their bits, least
    significant first, fill the input registers in the problem's register order.

    Otherwise each shot takes `problem.random_bytes_per_shot` bytes of the stream, and the
    problem builds its inputs from them and from the shot's index in the run.
    """
    if problem.random_inputs is not None:
        per_shot = problem.random_bytes_per_shot
        stream = hashlib.shake_256(seed + b'inputs' + chunk.to_bytes(8, 'little')).digest(shots * per_shot)
        rows = np.frombuffer(stream, dtype=np.uint8).reshape(shots, per_shot)
        return problem.random_inputs(rows, chunk * CHUNK_SHOTS)

    total_bits = sum(r.size for r in problem.inputs)
    bytes_per_shot = -(-total_bits // 8)
    stream = hashlib.shake_256(seed + b'inputs' + chunk.to_bytes(8, 'little')).digest(shots * bytes_per_shot)
    rows = np.frombuffer(stream, dtype=np.uint8).reshape(shots, bytes_per_shot)
    bits = np.unpackbits(rows, axis=1, bitorder='little')[:, :total_bits].T.astype(bool)
    inputs, offset = {}, 0
    for register in problem.inputs:
        inputs[register.name] = np.ascontiguousarray(bits[offset:offset + register.size])
        offset += register.size
    return inputs


def chunks(shots: int) -> list[tuple[int, int]]:
    """`(chunk index, shots in chunk)` covering `shots` random shots."""
    if shots <= 0 or shots % BATCH_SIZE:
        raise ValueError(f'The number of random shots must be a positive multiple of {BATCH_SIZE}, got {shots}.')
    return [(c, min(CHUNK_SHOTS, shots - c * CHUNK_SHOTS)) for c in range(-(-shots // CHUNK_SHOTS))]
