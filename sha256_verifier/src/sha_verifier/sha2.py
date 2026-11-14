"""Reference SHA-2 compression function (FIPS 180-4), vectorized over many inputs.

This is the verifier's definition of the right answer. `hashlib` cannot serve as one
directly because it always pads, and the benchmark task is a raw compression of an
arbitrary block. `hashlib` is used in the tests to validate this module instead.

Circuit generators must not import this module: a submission and the reference it is
checked against should not be able to share a bug.

Words are held as numpy unsigned integers, one row per input: a block is an array of
shape `(n, 16)` and a chaining state is `(n, 8)`.
"""

from __future__ import annotations

import dataclasses
import functools
import math

import numpy as np


def _primes(count: int) -> list[int]:
    primes: list[int] = []
    candidate = 2
    while len(primes) < count:
        if all(candidate % p for p in primes):
            primes.append(candidate)
        candidate += 1
    return primes


def _icbrt(n: int) -> int:
    """Floor of the cube root of a non-negative integer."""
    x = 1 << -(-n.bit_length() // 3)  # A power of two at or above the root.
    while True:
        y = (2 * x + n // (x * x)) // 3
        if y >= x:
            return x
        x = y


@dataclasses.dataclass(frozen=True)
class Sha2Params:
    """One member of the SHA-2 family: SHA-256 or SHA-512 style.

    `big_sigma*` are three right-rotation amounts; `small_sigma*` are two right-rotation
    amounts and one right-shift amount.
    """
    name: str
    word_bits: int
    rounds: int
    big_sigma0: tuple[int, int, int]
    big_sigma1: tuple[int, int, int]
    small_sigma0: tuple[int, int, int]
    small_sigma1: tuple[int, int, int]

    @property
    def dtype(self) -> np.dtype:
        return np.dtype(f'uint{self.word_bits}')

    @property
    def word_bytes(self) -> int:
        return self.word_bits // 8

    @property
    def block_bytes(self) -> int:
        return 16 * self.word_bytes

    @functools.cached_property
    def iv(self) -> tuple[int, ...]:
        """Initial hash value: fractional bits of the square roots of the first 8 primes."""
        w = self.word_bits
        return tuple(math.isqrt(p << (2 * w)) & ((1 << w) - 1) for p in _primes(8))

    @functools.cached_property
    def k(self) -> tuple[int, ...]:
        """Round constants: fractional bits of the cube roots of the first primes."""
        w = self.word_bits
        return tuple(_icbrt(p << (3 * w)) & ((1 << w) - 1) for p in _primes(self.rounds))


SHA256 = Sha2Params(
    name='sha256', word_bits=32, rounds=64,
    big_sigma0=(2, 13, 22), big_sigma1=(6, 11, 25),
    small_sigma0=(7, 18, 3), small_sigma1=(17, 19, 10),
)

SHA512 = Sha2Params(
    name='sha512', word_bits=64, rounds=80,
    big_sigma0=(28, 34, 39), big_sigma1=(14, 18, 41),
    small_sigma0=(1, 8, 7), small_sigma1=(19, 61, 6),
)


def compress(params: Sha2Params, state: np.ndarray, block: np.ndarray) -> np.ndarray:
    """The SHA-2 compression function, including the final feed-forward addition.

    Args:
        state: Chaining values, shape `(n, 8)` or `(8,)` (broadcast over all blocks).
        block: Message blocks, shape `(n, 16)`.

    Returns:
        The next chaining values, shape `(n, 8)`.
    """
    dtype, bits = params.dtype, params.word_bits
    block = np.asarray(block)
    if block.dtype != dtype or block.ndim != 2 or block.shape[1] != 16:
        raise ValueError(f'block must be {dtype} with shape (n, 16), got {block.dtype} {block.shape}.')
    state = np.asarray(state)
    if state.dtype != dtype or state.shape[-1] != 8:
        raise ValueError(f'state must be {dtype} with shape (n, 8) or (8,), got {state.dtype} {state.shape}.')
    state = np.broadcast_to(state, (len(block), 8))

    def rotr(x: np.ndarray, n: int) -> np.ndarray:
        return (x >> dtype.type(n)) | (x << dtype.type(bits - n))

    def big_sigma(x: np.ndarray, r: tuple[int, int, int]) -> np.ndarray:
        return rotr(x, r[0]) ^ rotr(x, r[1]) ^ rotr(x, r[2])

    def small_sigma(x: np.ndarray, r: tuple[int, int, int]) -> np.ndarray:
        return rotr(x, r[0]) ^ rotr(x, r[1]) ^ (x >> dtype.type(r[2]))

    # Unsigned array arithmetic wraps, which is the addition mod 2^w that SHA-2 specifies.
    w = [block[:, t].copy() for t in range(16)]  # Rolling window: w[t % 16] is W_t.
    a, b, c, d, e, f, g, h = (state[:, i].copy() for i in range(8))
    for t in range(params.rounds):
        if t >= 16:
            w[t % 16] = (small_sigma(w[(t - 2) % 16], params.small_sigma1) + w[(t - 7) % 16]
                         + small_sigma(w[(t - 15) % 16], params.small_sigma0) + w[t % 16])
        t1 = (h + big_sigma(e, params.big_sigma1) + ((e & f) ^ (~e & g))
              + dtype.type(params.k[t]) + w[t % 16])
        t2 = big_sigma(a, params.big_sigma0) + ((a & b) ^ (a & c) ^ (b & c))
        a, b, c, d, e, f, g, h = t1 + t2, a, b, c, d + t1, e, f, g
    return np.stack([a, b, c, d, e, f, g, h], axis=1) + state


def pad(params: Sha2Params, message: bytes) -> bytes:
    """`message` with SHA-2 padding appended; a whole number of blocks."""
    length_bytes = 2 * params.word_bytes
    zeros = -(len(message) + 1 + length_bytes) % params.block_bytes
    return message + b'\x80' + bytes(zeros) + (8 * len(message)).to_bytes(length_bytes, 'big')


def words_from_bytes(params: Sha2Params, data: bytes) -> np.ndarray:
    """Big-endian words of `data`, shape `(n_blocks, 16)`. `data` must be whole blocks."""
    if len(data) % params.block_bytes:
        raise ValueError(f'Expected a multiple of {params.block_bytes} bytes, got {len(data)}.')
    return np.frombuffer(data, dtype=params.dtype.newbyteorder('>')).astype(params.dtype).reshape(-1, 16)


def bytes_from_words(params: Sha2Params, words: np.ndarray) -> bytes:
    """The big-endian byte string of `words` (any shape, row-major)."""
    return np.asarray(words, dtype=params.dtype).astype(params.dtype.newbyteorder('>')).tobytes()


def digest(params: Sha2Params, message: bytes) -> bytes:
    """The full hash of `message`, by chaining `compress` over its padded blocks."""
    state = np.array(params.iv, dtype=params.dtype)
    for block in words_from_bytes(params, pad(params, message)):
        state = compress(params, state, block[None, :])[0]
    return bytes_from_words(params, state)
