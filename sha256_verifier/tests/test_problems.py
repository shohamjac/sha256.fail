import hashlib

import kickmix as km
import numpy as np
import pytest

from sha_verifier import bits, problems, sha2

SPEC = problems.SHA256_COMPRESS_V1

# Published in docs/sha256-compress-v1.md: block bytes -> digest bytes.
VECTORS = {
    bytes(64): 'da5698be17b9b46962335799779fbeca8ce5d491c0d26243bafef9ea1837a9d8',
    b'\xff' * 64: 'ef0c748df4da50a8d6c43c013edc3ce76c9d9fa9a1458ade56eb86c0a64492d2',
    bytes(range(64)): 'fc99a2df88f42a7a7bb9d18033cdc6a20256755f9d5b9a5044a9cc315abe84a7',
    b'abc\x80' + bytes(59) + b'\x18': 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
    b'\x80' + bytes(63): 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
}

# SHA-256 of the directed test set, packed 8 register bits per byte, least significant
# first, shot after shot. Changing either value changes the contract: add a new problem
# version instead.
DIRECTED_COUNT = 1179
DIRECTED_INPUTS_SHA256 = '6d4e609587811d84213871de33cc4e3ea371188092ae49aecad65747d854c7e2'
DIRECTED_OUTPUTS_SHA256 = 'c84f4e941a57469ba9b9ee355d2571b5c5769916f1df7472139b270c57cb0cd7'


def block_bits(blocks: bytes) -> np.ndarray:
    return bits.words_to_bits(sha2.words_from_bytes(sha2.SHA256, blocks))


def digest_bytes(digest_bits: np.ndarray) -> list[bytes]:
    words = bits.bits_to_words(digest_bits, 32)
    return [sha2.bytes_from_words(sha2.SHA256, row) for row in words]


def fingerprint(register_bits: np.ndarray) -> str:
    return hashlib.sha256(np.packbits(register_bits, bitorder='little').tobytes()).hexdigest()


def test_registry():
    assert problems.get('sha256-compress-v1') is SPEC
    assert all(problems.PROBLEMS[name].name == name for name in problems.PROBLEMS)
    with pytest.raises(ValueError, match='sha256-compress-v1'):
        problems.get('sha1')


def test_registers():
    assert [(r.name, r.size, r.role) for r in SPEC.registers] == [
        ('block', 512, 'input'), ('digest', 256, 'output')]
    assert [r.name for r in SPEC.inputs] == ['block']
    assert [r.name for r in SPEC.outputs] == ['digest']


@pytest.mark.parametrize('block,expected', VECTORS.items(), ids=['zero', 'ones', 'count', 'abc', 'empty'])
def test_published_vectors(block, expected):
    out = SPEC.reference({'block': block_bits(block)})
    assert list(out) == ['digest'] and out['digest'].shape == (256, 1) and out['digest'].dtype == bool
    assert digest_bytes(out['digest'])[0].hex() == expected


def test_published_bit_positions():
    """The worked example in the contract document: the padded empty message."""
    block = block_bits(b'\x80' + bytes(63))
    assert np.flatnonzero(block[:, 0]).tolist() == [31]  # Top bit of W_0.
    digest = SPEC.reference({'block': block})['digest'][:, 0]
    # H_0 = 0xe3b0c442, so its bit 1 and bit 6 are the lowest set bits.
    assert np.flatnonzero(digest[:32]).tolist() == [k for k in range(32) if (0xe3b0c442 >> k) & 1]
    assert np.flatnonzero(digest).tolist()[:2] == [1, 6]


def test_published_byte_formula():
    """Bit b of byte i is at register offset 32 (i // 4) + 8 (3 - i % 4) + b."""
    for i in range(64):
        for b in range(8):
            block = bytearray(64)
            block[i] = 1 << b
            offset = 32 * (i // 4) + 8 * (3 - i % 4) + b
            assert np.flatnonzero(block_bits(bytes(block))[:, 0]).tolist() == [offset]


def test_published_example_digest_offsets():
    digest = SPEC.reference({'block': block_bits(b'\x80' + bytes(63))})['digest'][:, 0]
    assert np.flatnonzero(digest[:32]).tolist() == [1, 6, 10, 14, 15, 20, 21, 23, 24, 25, 29, 30, 31]


def test_published_directed_breakdown():
    assert 8 + 512 + 512 + 32 + 2 + 113 == DIRECTED_COUNT


def test_reference_is_sha256_for_every_single_block_message_length():
    rng = np.random.default_rng(5)
    messages = [rng.bytes(length) for length in range(56) for _ in range(10)]
    blocks = b''.join(sha2.pad(sha2.SHA256, m) for m in messages)
    out = SPEC.reference({'block': block_bits(blocks)})['digest']
    assert digest_bytes(out) == [hashlib.sha256(m).digest() for m in messages]


def test_reference_on_random_blocks_matches_hashlib():
    """Hashing a 64-byte message compresses that raw block, then a fixed padding block."""
    rng = np.random.default_rng(6)
    n = 500
    raw = rng.bytes(64 * n)
    out = SPEC.reference({'block': block_bits(raw)})['digest']
    padding = sha2.words_from_bytes(sha2.SHA256, sha2.pad(sha2.SHA256, bytes(64)))[1:]
    final = sha2.compress(sha2.SHA256, bits.bits_to_words(out, 32), np.repeat(padding, n, axis=0))
    for i in range(n):
        assert sha2.bytes_from_words(sha2.SHA256, final[i]) == hashlib.sha256(raw[64 * i:64 * i + 64]).digest()


def test_directed_inputs_are_frozen():
    inputs = SPEC.directed_inputs()
    assert list(inputs) == ['block']
    assert inputs['block'].shape == (512, DIRECTED_COUNT) and inputs['block'].dtype == bool
    assert fingerprint(inputs['block']) == DIRECTED_INPUTS_SHA256
    assert fingerprint(SPEC.reference(inputs)['digest']) == DIRECTED_OUTPUTS_SHA256


def test_directed_inputs_content():
    block = SPEC.directed_inputs()['block']
    weights = block.sum(axis=0)
    assert weights[0] == 0 and weights[1] == 512  # All-zero and all-one blocks come first.
    assert (weights == 1).sum() >= 512 and (weights == 511).sum() >= 512  # Every single bit.
    singles = block[:, weights == 1]
    assert sorted(np.argmax(singles, axis=0).tolist())[:3] == [0, 1, 2]
    assert len({np.packbits(column).tobytes() for column in block.T}) > DIRECTED_COUNT - 10


def test_allowed_instructions():
    allowed = SPEC.allowed_instructions
    assert 'Z_POW' not in allowed
    assert {'CCX', 'HMR', 'R', 'CZ', 'PUSH_CONDITION'} <= allowed
    assert len(allowed) == 20


EXAMPLES = {
    'X': 'X q0', 'CX': 'CX q0 q1', 'CCX': 'CCX q0 q1 q2', 'SWAP': 'SWAP q0 q1',
    'CSWAP': 'CSWAP q0 q1 q2', 'Z': 'Z q0', 'CZ': 'CZ q0 q1', 'CCZ': 'CCZ q0 q1 q2',
    'NEG': 'NEG', 'R': 'R q0', 'HMR': 'HMR q0 b0', 'BIT_INVERT': 'BIT_INVERT b0',
    'BIT_STORE0': 'BIT_STORE0 b0', 'BIT_STORE1': 'BIT_STORE1 b0',
    'PUSH_CONDITION': 'PUSH_CONDITION if b0', 'POP_CONDITION': 'POP_CONDITION',
    'REGISTER': 'REGISTER r0 "a"', 'APPEND_TO_REGISTER': 'APPEND_TO_REGISTER q0 r0',
    'DEBUG_PRINT': 'DEBUG_PRINT q0', 'INFO_TAG': 'INFO_TAG "x"', 'Z_POW': 'Z_POW q0 0.25',
}


def test_instruction_names_are_kickmix_names():
    """Every allowed name, and `Z_POW`, is what Kickmix calls that instruction."""
    assert set(EXAMPLES) == SPEC.allowed_instructions | {'Z_POW'}
    for name, text in EXAMPLES.items():
        circuit = km.Circuit(text)
        if name in ('REGISTER', 'APPEND_TO_REGISTER'):
            # Kickmix folds these into the circuit's register table instead of its operations.
            assert circuit.num_registers == 1 and len(circuit) == 0, name
        else:
            stats = dict(circuit.operation_statistics())
            assert stats == {name: 1}, (name, stats)


def test_toffoli_like_matches_kickmix():
    for name, text in EXAMPLES.items():
        counted = km.Circuit(text).operation_statistics().num_toffoli_like
        assert counted == (1 if name in problems.TOFFOLI_LIKE else 0), name
