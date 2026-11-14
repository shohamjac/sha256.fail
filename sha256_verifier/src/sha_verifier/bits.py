"""Conversion between words and register bit arrays.

Register bit arrays are boolean with shape `(n_qubits, n_shots)`, the layout Kickmix's
`Simulator.write_across_shots` and `read_across_shots` use.

Bit order: a register holding words `x_0, x_1, ...` of `w` bits stores bit `k` of `x_j`
(bit 0 is the least significant) at register offset `w * j + k`. Each word is therefore
little-endian within the register, which is Kickmix's convention for integers, so a
circuit can hand a 32-qubit slice straight to an adder.
"""

from __future__ import annotations

import numpy as np


def words_to_bits(words: np.ndarray) -> np.ndarray:
    """Words of shape `(n_shots, n_words)` to bits of shape `(n_words * w, n_shots)`."""
    words = np.asarray(words)
    if words.ndim != 2 or words.dtype.kind != 'u':
        raise ValueError(f'Expected unsigned words of shape (n_shots, n_words), got {words.dtype} {words.shape}.')
    n_shots, n_words = words.shape
    little = words.astype(words.dtype.newbyteorder('<'), copy=False)
    as_bytes = np.ascontiguousarray(little).view(np.uint8).reshape(n_shots, n_words * words.dtype.itemsize)
    return np.unpackbits(as_bytes, axis=1, bitorder='little').T.astype(bool)


def bits_to_words(bits: np.ndarray, word_bits: int) -> np.ndarray:
    """Bits of shape `(n_words * word_bits, n_shots)` to words of shape `(n_shots, n_words)`."""
    bits = np.asarray(bits)
    if bits.ndim != 2 or bits.shape[0] % word_bits or word_bits % 8:
        raise ValueError(f'Expected bits of shape (n_words * {word_bits}, n_shots), got {bits.shape}.')
    as_bytes = np.packbits(bits.T.astype(bool), axis=1, bitorder='little')
    dtype = np.dtype(f'uint{word_bits}')
    return np.ascontiguousarray(as_bytes).view(dtype.newbyteorder('<')).astype(dtype)
