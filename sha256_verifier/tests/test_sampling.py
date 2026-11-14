import hashlib

import numpy as np
import pytest

import toy
from sha_verifier import problems, sampling

SHA = problems.SHA256_COMPRESS_V1
CIRCUIT = 'ab' * 32


def test_seed_depends_on_every_component():
    base = sampling.derive_seed(SHA, CIRCUIT, 'salt')
    assert len(base) == 32
    assert base == sampling.derive_seed(SHA, CIRCUIT, 'salt')
    assert base != sampling.derive_seed(toy.PROBLEM, CIRCUIT, 'salt')
    assert base != sampling.derive_seed(SHA, 'cd' * 32, 'salt')
    assert base != sampling.derive_seed(SHA, CIRCUIT, 'salt2')
    assert base != sampling.derive_seed(SHA, CIRCUIT, '')


def test_seed_fields_cannot_be_shifted_into_each_other():
    assert sampling.derive_seed(SHA, CIRCUIT + 'a', 'b') != sampling.derive_seed(SHA, CIRCUIT, 'ab')


def test_scheme_v1_is_frozen():
    """Pinned values: changing how seeds or inputs are derived must be a new scheme."""
    seed = sampling.derive_seed(SHA, CIRCUIT, 'salt')
    assert seed.hex() == hashlib.sha256(
        b'sha-verifier/seed/v1\x00sha256-compress-v1\x00' + CIRCUIT.encode() + b'\x00salt').hexdigest()
    block = sampling.random_inputs(SHA, seed, chunk=3, shots=2)['block']
    stream = hashlib.shake_256(seed + b'inputs' + (3).to_bytes(8, 'little')).digest(128)
    for shot in range(2):
        for offset in (0, 1, 8, 511):
            byte = stream[64 * shot + offset // 8]
            assert block[offset, shot] == bool((byte >> (offset % 8)) & 1)
    assert sampling.simulator_seed(seed, 'random', 3) == int.from_bytes(
        hashlib.sha256(seed + b'simrandom' + (3).to_bytes(8, 'little')).digest(), 'big')


def test_random_inputs_shape_and_determinism():
    seed = sampling.derive_seed(SHA, CIRCUIT, '')
    first = sampling.random_inputs(SHA, seed, 0, 512)
    assert list(first) == ['block'] and first['block'].shape == (512, 512) and first['block'].dtype == bool
    assert np.array_equal(first['block'], sampling.random_inputs(SHA, seed, 0, 512)['block'])
    assert not np.array_equal(first['block'], sampling.random_inputs(SHA, seed, 1, 512)['block'])
    # A shorter chunk is a prefix of a longer one.
    assert np.array_equal(first['block'][:, :256], sampling.random_inputs(SHA, seed, 0, 256)['block'])


def test_random_inputs_look_uniform():
    seed = sampling.derive_seed(SHA, CIRCUIT, '')
    block = sampling.random_inputs(SHA, seed, 0, 4096)['block']
    assert abs(block.mean() - 0.5) < 0.005
    assert abs(block.mean(axis=1) - 0.5).max() < 0.05  # Every bit position.
    assert len({np.packbits(column).tobytes() for column in block.T}) == 4096


def test_random_inputs_split_across_registers():
    """Two 4-bit input registers take one byte per shot: a from its low bits, b from its high."""
    seed = sampling.derive_seed(toy.PROBLEM, CIRCUIT, '')
    inputs = sampling.random_inputs(toy.PROBLEM, seed, 0, 256)
    assert list(inputs) == ['a', 'b'] and inputs['a'].shape == (4, 256)
    stream = hashlib.shake_256(seed + b'inputs' + (0).to_bytes(8, 'little')).digest(256)
    weights = 1 << np.arange(4)
    assert (inputs['a'].T @ weights).tolist() == [byte & 15 for byte in stream]
    assert (inputs['b'].T @ weights).tolist() == [byte >> 4 for byte in stream]


def test_chunks():
    assert sampling.chunks(256) == [(0, 256)]
    assert sampling.chunks(4096) == [(0, 4096)]
    assert sampling.chunks(4096 + 512) == [(0, 4096), (1, 512)]
    assert len(sampling.chunks(1 << 20)) == 256
    assert sum(shots for _, shots in sampling.chunks(1 << 20)) == 1 << 20
    for bad in (0, -256, 100, 257):
        with pytest.raises(ValueError):
            sampling.chunks(bad)


def test_simulator_seed_fits_kickmix_and_varies():
    seed = sampling.derive_seed(SHA, CIRCUIT, '')
    seeds = {sampling.simulator_seed(seed, phase, chunk) for phase in ('directed', 'random') for chunk in range(4)}
    assert len(seeds) == 8 and all(0 <= s < 2**256 for s in seeds)
