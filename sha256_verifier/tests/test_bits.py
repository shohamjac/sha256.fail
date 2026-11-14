import numpy as np
import pytest

from sha_verifier import bits


def test_bit_k_of_word_j_is_at_offset_32j_plus_k():
    words = np.zeros((3, 16), dtype=np.uint32)
    words[0, 0] = 1  # Shot 0: least significant bit of word 0.
    words[1, 1] = 0x80000000  # Shot 1: most significant bit of word 1.
    words[2, 15] = 0b101  # Shot 2: bits 0 and 2 of word 15.
    out = bits.words_to_bits(words)
    assert out.shape == (512, 3) and out.dtype == bool
    assert np.flatnonzero(out[:, 0]).tolist() == [0]
    assert np.flatnonzero(out[:, 1]).tolist() == [63]
    assert np.flatnonzero(out[:, 2]).tolist() == [480, 482]


@pytest.mark.parametrize('word_bits', [32, 64])
def test_round_trip(word_bits):
    rng = np.random.default_rng(0)
    dtype = np.dtype(f'uint{word_bits}')
    words = rng.integers(0, 2**word_bits, size=(37, 8), dtype=dtype)
    as_bits = bits.words_to_bits(words)
    assert as_bits.shape == (8 * word_bits, 37)
    back = bits.bits_to_words(as_bits, word_bits)
    assert back.dtype == dtype and np.array_equal(back, words)


def test_matches_shift_and_mask_definition():
    rng = np.random.default_rng(1)
    words = rng.integers(0, 2**32, size=(5, 4), dtype=np.uint32)
    out = bits.words_to_bits(words)
    for shot in range(5):
        for j in range(4):
            for k in range(32):
                assert out[32 * j + k, shot] == bool((int(words[shot, j]) >> k) & 1)


def test_rejects_bad_shapes():
    with pytest.raises(ValueError):
        bits.words_to_bits(np.zeros(16, dtype=np.uint32))
    with pytest.raises(ValueError):
        bits.words_to_bits(np.zeros((2, 16), dtype=np.int32))
    with pytest.raises(ValueError):
        bits.bits_to_words(np.zeros((500, 2), dtype=bool), 32)
