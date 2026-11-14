"""The reference compression function, checked against `hashlib` and published vectors."""

import hashlib

import numpy as np
import pytest

from sha_verifier import sha2

FAMILY = [(sha2.SHA256, hashlib.sha256), (sha2.SHA512, hashlib.sha512)]
IDS = ['sha256', 'sha512']

# FIPS 180-4 example digests.
KNOWN_SHA256 = {
    b'': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    b'abc': 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
    b'abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq':
        '248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1',
}


def test_sha256_constants():
    assert sha2.SHA256.iv == (0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                              0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19)
    k = sha2.SHA256.k
    assert len(k) == 64
    assert k[:4] == (0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5)
    assert k[-1] == 0xc67178f2


def test_sha512_constants():
    assert sha2.SHA512.iv[0] == 0x6a09e667f3bcc908
    assert sha2.SHA512.iv[7] == 0x5be0cd19137e2179
    k = sha2.SHA512.k
    assert len(k) == 80
    assert (k[0], k[-1]) == (0x428a2f98d728ae22, 0x6c44198c4a475817)


@pytest.mark.parametrize('message,expected', KNOWN_SHA256.items())
def test_known_sha256_digests(message, expected):
    assert hashlib.sha256(message).hexdigest() == expected
    assert sha2.digest(sha2.SHA256, message).hex() == expected


@pytest.mark.parametrize('params,hasher', FAMILY, ids=IDS)
def test_digest_matches_hashlib_at_every_length(params, hasher):
    """Covers every padding layout, including the one- to two-block boundaries."""
    rng = np.random.default_rng(1)
    for length in range(3 * params.block_bytes + 2):
        message = rng.bytes(length)
        assert sha2.digest(params, message) == hasher(message).digest(), length


@pytest.mark.parametrize('params,hasher', FAMILY, ids=IDS)
def test_single_block_compress_matches_hashlib(params, hasher):
    """For a message that pads to one block, one compression from the IV is the digest."""
    rng = np.random.default_rng(2)
    longest = params.block_bytes - 2 * params.word_bytes - 1  # 55 for SHA-256.
    messages = [rng.bytes(length) for length in range(longest + 1) for _ in range(20)]
    blocks = sha2.words_from_bytes(params, b''.join(sha2.pad(params, m) for m in messages))
    assert blocks.shape == (len(messages), 16)
    states = sha2.compress(params, np.array(params.iv, dtype=params.dtype), blocks)
    for message, state in zip(messages, states):
        assert sha2.bytes_from_words(params, state) == hasher(message).digest()


@pytest.mark.parametrize('params,hasher', FAMILY, ids=IDS)
def test_compress_on_arbitrary_blocks_matches_hashlib(params, hasher):
    """A message of exactly one block is hashed as that raw block, then a pure-padding block.

    So `hashlib` checks `compress` on uniformly random blocks (the benchmark's input
    distribution) and, in the second step, on arbitrary chaining states.
    """
    rng = np.random.default_rng(3)
    n = 3000
    raw = rng.bytes(n * params.block_bytes)
    blocks = sha2.words_from_bytes(params, raw)
    padding_block = sha2.words_from_bytes(params, sha2.pad(params, bytes(params.block_bytes)))[1:]

    middle = sha2.compress(params, np.array(params.iv, dtype=params.dtype), blocks)
    final = sha2.compress(params, middle, np.repeat(padding_block, n, axis=0))
    for i in range(n):
        message = raw[i * params.block_bytes:(i + 1) * params.block_bytes]
        assert sha2.bytes_from_words(params, final[i]) == hasher(message).digest()


@pytest.mark.parametrize('params', [sha2.SHA256, sha2.SHA512], ids=IDS)
def test_compress_batch_equals_one_at_a_time(params):
    rng = np.random.default_rng(4)
    blocks = sha2.words_from_bytes(params, rng.bytes(50 * params.block_bytes))
    states = sha2.words_from_bytes(params, rng.bytes(50 * params.block_bytes))[:, :8]
    batch = sha2.compress(params, states, blocks)
    for i in range(50):
        assert np.array_equal(sha2.compress(params, states[i], blocks[i:i + 1])[0], batch[i])


def test_compress_does_not_modify_its_arguments():
    params = sha2.SHA256
    blocks = sha2.words_from_bytes(params, bytes(range(64)) * 3)
    state = np.array(params.iv, dtype=np.uint32)
    blocks_before, state_before = blocks.copy(), state.copy()
    sha2.compress(params, state, blocks)
    assert np.array_equal(blocks, blocks_before) and np.array_equal(state, state_before)


def test_compress_rejects_wrong_dtype_or_shape():
    params = sha2.SHA256
    iv = np.array(params.iv, dtype=np.uint32)
    with pytest.raises(ValueError):
        sha2.compress(params, iv, np.zeros((2, 16), dtype=np.uint64))
    with pytest.raises(ValueError):
        sha2.compress(params, iv, np.zeros((2, 15), dtype=np.uint32))
    with pytest.raises(ValueError):
        sha2.compress(params, iv.astype(np.int64), np.zeros((2, 16), dtype=np.uint32))


def test_pad_block_counts_at_boundaries():
    params = sha2.SHA256
    assert [len(sha2.pad(params, bytes(n))) // 64 for n in (0, 55, 56, 63, 64, 119, 120)] == [1, 1, 2, 2, 2, 2, 3]
    assert sha2.pad(params, b'abc') == b'abc\x80' + bytes(59) + b'\x18'


def test_words_are_big_endian_over_bytes():
    params = sha2.SHA256
    words = sha2.words_from_bytes(params, bytes(range(64)))
    assert words.shape == (1, 16) and words.dtype == np.uint32
    assert words[0, 0] == 0x00010203 and words[0, 15] == 0x3c3d3e3f
    assert sha2.bytes_from_words(params, words) == bytes(range(64))
    with pytest.raises(ValueError):
        sha2.words_from_bytes(params, bytes(63))
