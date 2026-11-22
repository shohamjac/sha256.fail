"""The problem `bitcoin-mining-v1`: its function and its tests.

The reference function is checked here against `hashlib` and plain Python integers, which
share no code with it. A circuit is run end to end in test_bitcoin_submission.py.
"""

import hashlib

import numpy as np
import pytest

from sha_verifier import bitcoin, problems, sampling
from sha_verifier.bitcoin_blocks import BLOCKS, Block

SPEC = problems.BITCOIN_MINING_V1

# Published in docs/bitcoin-mining-v1.md: height, bits as Bitcoin shows it, coinbase bytes,
# leading zero bits of the hash, one-bit masks that keep the hit.
PUBLISHED_BLOCKS = [
    (20013, '1d00ffff', 134, 33, 64), (20014, '1d00ffff', 134, 32, 64),
    (69013, '1c0168fd', 134, 41, 57), (69014, '1c0168fd', 135, 41, 57),
    (100006, '1b04864c', 135, 48, 50), (100007, '1b04864c', 134, 47, 50),
    (199962, '1a05db8b', 142, 53, 42), (199976, '1a05db8b', 142, 54, 42),
    (279709, '1903071f', 175, 63, 33), (279737, '1903071f', 176, 62, 33),
    (419501, '180526fd', 146, 73, 27), (419904, '180526fd', 173, 71, 27),
    (739788, '17096a20', 236, 81, 20), (739815, '17096a20', 309, 78, 19),
    (976830, '17021673', 291, 79, 17), (976835, '17021673', 289, 80, 17),
]

# SHA-256 over the registers in order, each packed 8 bits per byte, least significant
# first, shot after shot; and over the expected phases packed the same way. Changing any of
# these changes the contract: add a new problem version instead.
DIRECTED_COUNT = 2848
DIRECTED_FLIPS = 635
DIRECTED_INPUTS_SHA256 = 'aa2b0cb81749c4d4d1f99e8d40d98cefb1ec80e063c03388eb270c3479791a2c'
DIRECTED_PHASES_SHA256 = '35cfbd0bd88b0f955d11f3527fd2840a8e95f7dcd34f409b0e2137ed2f9057c5'
# Chunk 3 of the random tests for circuit hash 'abab…' and salt 'pin'.
RANDOM_INPUTS_SHA256 = 'e978fe0a91311fd1cc77faf14310fabd896c8aa1ba439eea4cb6751442da0efb'
RANDOM_PHASES_SHA256 = 'a9de3f2ba39466e510f43ad4212af4c876f813c89bf0785702263e0ea5914366'


def sha256d(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def compact_target(header: bytes) -> int:
    return int.from_bytes(header[72:75], 'little') << 8 * (header[75] - 3)


def flips_by_hashlib(header: bytes, mask: bytes) -> bool:
    """The function of the contract for a whole header, with nothing but hashlib and integers."""
    digest = sha256d(header)
    masked = digest[:20] + bytes(a ^ b for a, b in zip(digest[20:], mask))
    return int.from_bytes(masked, 'little') < compact_target(header)


def fingerprint(registers: dict) -> str:
    packed = hashlib.sha256()
    for name, _, _ in bitcoin.REGISTERS:
        packed.update(np.packbits(registers[name], bitorder='little').tobytes())
    return packed.hexdigest()


def phases_fingerprint(flips: np.ndarray) -> str:
    return hashlib.sha256(np.packbits(flips, bitorder='little').tobytes()).hexdigest()


def stack(shots: list[bitcoin.Fields]) -> bitcoin.Fields:
    return {name: np.concatenate([shot[name] for shot in shots]) for name in shots[0]}


def with_mask(fields: bitcoin.Fields, mask: bytes) -> bitcoin.Fields:
    return {**fields, 'mask': np.frombuffer(mask, dtype='>u4').astype(np.uint32)[None, :]}


def phase_of(fields: bitcoin.Fields) -> list[bool]:
    return bitcoin.phase(bitcoin.to_registers(fields)).tolist()


# The problem's shape.


def test_registry_and_registers():
    assert problems.get('bitcoin-mining-v1') is SPEC
    assert [(r.name, r.size, r.kind) for r in SPEC.registers] == [
        ('extranonce', 48, 'qubit'), ('nonce', 32, 'qubit'), ('midstate', 256, 'bit'), ('tail', 464, 'bit'),
        ('version', 32, 'bit'), ('prev_hash', 256, 'bit'), ('time', 32, 'bit'), ('bits', 32, 'bit'),
        ('mask', 96, 'bit')]
    assert SPEC.outputs == () and len(SPEC.inputs) == 9
    assert SPEC.random_shots == 1 << 20
    assert SPEC.allowed_instructions == problems.SHA256_COMPRESS_V1.allowed_instructions
    assert SPEC.reference({}) == {}


# The real blocks, checked without the verifier's own SHA-256.


def test_blocks_are_the_published_ones():
    assert [b.height for b in BLOCKS] == [row[0] for row in PUBLISHED_BLOCKS]
    for block, (_, shown_bits, coinbase_bytes, zeros, _) in zip(BLOCKS, PUBLISHED_BLOCKS):
        assert block.header[72:76][::-1].hex() == shown_bits
        assert len(block.coinbase) == coinbase_bytes
        assert 256 - int.from_bytes(sha256d(block.header), 'little').bit_length() == zeros


@pytest.mark.parametrize('block', BLOCKS, ids=lambda b: str(b.height))
def test_block_is_a_real_coinbase_only_block(block):
    assert len(block.header) == 80
    assert sha256d(block.coinbase) == block.header[36:68]  # One transaction: its id is the merkle root.
    assert int.from_bytes(sha256d(block.header), 'little') < compact_target(block.header)
    assert 6 <= len(block.coinbase) % 64 <= 55
    assert 0x17 <= block.header[75] <= 0x1d


@pytest.mark.parametrize('block', BLOCKS, ids=lambda b: str(b.height))
def test_function_gives_the_block_hash(block):
    fields = bitcoin.block_fields(block)
    words = bitcoin.block_hash(fields)
    assert words.astype('>u4').tobytes() == sha256d(block.header)
    assert phase_of(fields) == [True]


def test_blocks_cover_every_real_exponent_twice():
    exponents = [b.header[75] for b in BLOCKS]
    assert all(exponents.count(e) >= 2 for e in range(0x17, 0x1e))


def test_a_coinbase_that_does_not_fit_is_refused():
    for length in (64 + 5, 64 + 56, 128):
        with pytest.raises(ValueError, match='does not fit'):
            bitcoin.block_fields(Block(height=0, header=bytes(80), coinbase=bytes(length)))


# The published test vectors and bit order.

BLOCK_1 = dict(
    midstate=bytes.fromhex('0a066bebb4720ae534b6849209f878edd4ff18e00c2a340494d672b420907ac5'),
    extranonce=bytes.fromhex('eeac00000000'),
    tail=b'\x80' + bytes(55) + b'\x04\x30',
    version=bytes.fromhex('01000000'),
    prev_hash=bytes.fromhex('6fe28c0ab6f1b372c1a6a246ae63f74f931e8365e15a089c68d6190000000000'),
    time=bytes.fromhex('61bc6649'),
    bits=bytes.fromhex('ffff001d'),
    nonce=bytes.fromhex('01e36299'),
)
BLOCK_1_HASH = '00000000839a8e6886ab5951d76f411475428afc90947ee320161bbf18eb6048'


def test_published_vector_hash():
    words = bitcoin.block_hash(bitcoin.fields_from_bytes(**BLOCK_1))
    assert words.astype('>u4').tobytes()[::-1].hex() == BLOCK_1_HASH
    assert words.astype('>u4').tobytes()[20:].hex() == '5159ab86688e9a8300000000'


@pytest.mark.parametrize('mask,flipped', [
    ('00000000 00000000 00000000', True),
    ('00000000 0000647c 00000000', True),
    ('00000000 0000657c 00000000', False),
    ('00000000 00000000 80000000', False),
    ('00000000 00000000 00000080', False),
    ('ffffffff ffff0000 00000000', True),
])
def test_published_vector_masks(mask, flipped):
    assert phase_of(bitcoin.fields_from_bytes(**BLOCK_1, mask=bytes.fromhex(mask))) == [flipped]


def test_published_vector_next_nonce():
    assert phase_of(bitcoin.fields_from_bytes(**{**BLOCK_1, 'nonce': bytes.fromhex('02e36299')})) == [False]


def one_shot_registers(**changes) -> dict:
    blank = dict(midstate=bytes(32), extranonce=bytes(6), tail=bytes(58), version=bytes(4), prev_hash=bytes(32),
                 time=bytes(4), bits=bytes(4), nonce=bytes(4), mask=bytes(12))
    return bitcoin.to_registers(bitcoin.fields_from_bytes(**{**blank, **changes}))


def set_offsets(registers: dict) -> list[tuple[str, int]]:
    return [(name, int(k)) for name, bits_ in registers.items() for k in np.flatnonzero(bits_[:, 0])]


def single_bit(length: int, byte: int, bit: int) -> bytes:
    data = bytearray(length)
    data[byte] = 1 << bit
    return bytes(data)


def test_published_bit_order_of_the_coinbase_block():
    """Byte i of the coinbase's last block is in W_(i // 4), at bits 8 (3 - i % 4) and up."""
    for i in range(64):
        for b in range(8):
            j, k = i // 4, 8 * (3 - i % 4) + b
            if i < 6:
                got = set_offsets(one_shot_registers(extranonce=single_bit(6, i, b)))
                expected = ('extranonce', k) if j == 0 else ('extranonce', 32 + k - 16)
            else:
                got = set_offsets(one_shot_registers(tail=single_bit(58, i - 6, b)))
                expected = ('tail', k) if j == 1 else ('tail', 16 + 32 * (j - 2) + k)
            assert got == [expected], (i, b)


def test_published_bit_order_of_the_header_fields():
    for name, words in (('version', 1), ('prev_hash', 8), ('time', 1), ('bits', 1), ('nonce', 1), ('midstate', 8)):
        for i in range(4 * words):
            got = set_offsets(one_shot_registers(**{name: single_bit(4 * words, i, 3)}))
            assert got == [(name, 32 * (i // 4) + 8 * (3 - i % 4) + 3)], (name, i)


def test_published_mask_formula():
    """Bit p of the hash as an integer is masked by mask[32 (i // 4 - 5) + 8 (3 - i % 4) + p % 8], i = p // 8."""
    for p in range(160, 256):
        i = p // 8
        mask = (1 << (p - 160)).to_bytes(12, 'little')  # The integer's bit p, as digest bytes 20..31.
        assert set_offsets(one_shot_registers(mask=mask)) == [('mask', 32 * (i // 4 - 5) + 8 * (3 - i % 4) + p % 8)]


def test_published_target_formula():
    word = np.array([0xffff001d, 0x7316021f, 0x01000017], dtype=np.uint32)  # Header bytes, big-endian.
    exponent, mantissa = bitcoin.target(word)
    assert exponent.tolist() == [0x1d, 0x1f, 0x17] and mantissa.tolist() == [0x00ffff, 0x021673, 0x000001]
    registers = one_shot_registers(bits=bytes.fromhex('ffff001d'))
    assert sum(int(registers['bits'][k, 0]) << k for k in range(8)) == 0x1d  # e is bits[0 … 7].


@pytest.mark.parametrize('bits_hex', ['ffff0016', 'ffff0021', '00000017', '00008017'])
def test_targets_outside_the_range_are_refused(bits_hex):
    with pytest.raises(ValueError, match='outside the allowed range'):
        bitcoin.target(np.array([int(bits_hex, 16)], dtype=np.uint32))


# The function against hashlib, on made-up blocks.


def made_up_block(rng: np.random.Generator) -> Block:
    coinbase = rng.bytes(64 * int(rng.integers(1, 9)) + int(rng.integers(6, 56)))
    mantissa = int(rng.integers(1, 0x800000))
    bits_field = mantissa.to_bytes(3, 'little') + bytes([int(rng.integers(0x17, 0x21))])
    header = rng.bytes(36) + sha256d(coinbase) + rng.bytes(4) + bits_field + rng.bytes(4)
    return Block(height=0, header=header, coinbase=coinbase)


def test_phase_matches_hashlib_on_made_up_blocks():
    rng = np.random.default_rng(11)
    shots, expected = [], []
    for case in range(600):
        block = made_up_block(rng)
        top = int.from_bytes(sha256d(block.header)[20:], 'little')
        shift = 8 * (block.header[75] - 0x17)
        mantissa = int.from_bytes(block.header[72:75], 'little')
        # Random masks almost never give a hit, so most masks here aim near the target.
        quotient = [None, 0, mantissa - 1, mantissa, mantissa + 1, mantissa - 1 + (1 << 23),
                    int(rng.integers(0, mantissa))][case % 7]
        if quotient is None:
            mask = rng.bytes(12)
        else:
            low = int.from_bytes(rng.bytes(12), 'little') & ((1 << shift) - 1)
            mask = (top ^ (quotient << shift | low)).to_bytes(12, 'little')
        shots.append(with_mask(bitcoin.block_fields(block), mask))
        expected.append(flips_by_hashlib(block.header, mask))
    assert phase_of(stack(shots)) == expected
    assert 150 < sum(expected) < 300  # Both answers are well represented.


def test_registers_round_trip():
    rng = np.random.default_rng(12)
    fields = stack([with_mask(bitcoin.block_fields(made_up_block(rng)), rng.bytes(12)) for _ in range(20)])
    registers = bitcoin.to_registers(fields)
    assert list(registers) == [name for name, _, _ in bitcoin.REGISTERS]
    assert all(registers[name].shape == (size, 20) and registers[name].dtype == bool
               for name, size, _ in bitcoin.REGISTERS)
    back = bitcoin.from_registers(registers)
    assert all(np.array_equal(back[name], fields[name]) for name in fields)


# Directed tests.


def test_directed_tests_are_frozen():
    inputs = SPEC.directed_inputs()
    flips = SPEC.phase(inputs)
    assert inputs['mask'].shape == (96, DIRECTED_COUNT) == (96, len(BLOCKS) * bitcoin.SHOTS_PER_BLOCK)
    assert int(flips.sum()) == DIRECTED_FLIPS
    assert fingerprint(inputs) == DIRECTED_INPUTS_SHA256
    assert phases_fingerprint(flips) == DIRECTED_PHASES_SHA256


def test_directed_shots_of_each_block():
    inputs = SPEC.directed_inputs()
    flips = SPEC.phase(inputs).reshape(len(BLOCKS), bitcoin.SHOTS_PER_BLOCK)
    search = np.concatenate([inputs['extranonce'], inputs['nonce']])
    for index, (block, published) in enumerate(zip(BLOCKS, PUBLISHED_BLOCKS)):
        start = index * bitcoin.SHOTS_PER_BLOCK
        shots = {name: bits_[:, start:start + bitcoin.SHOTS_PER_BLOCK] for name, bits_ in inputs.items()}
        mined = {name: bits_[:, :1] for name, bits_ in shots.items()}
        assert all(np.array_equal(mined[name], column) for name, column
                   in bitcoin.to_registers(bitcoin.block_fields(block)).items())

        # As mined it is a hit; with the next nonce or any search bit flipped it is not.
        assert flips[index, 0] and not flips[index, 1:82].any()
        nonce = int.from_bytes(block.header[76:80], 'little')
        next_nonce = bitcoin.from_registers(shots)['nonce'][1, 0]
        assert int(next_nonce).to_bytes(4, 'big') == ((nonce + 1) % 2**32).to_bytes(4, 'little')
        changed = search[:, start + 2:start + 82] != search[:, start:start + 1]
        assert np.array_equal(changed, np.eye(80, dtype=bool))

        # Only the search register and the mask ever differ from the block.
        for name in ('midstate', 'tail', 'version', 'prev_hash', 'time', 'bits'):
            assert (shots[name] == mined[name]).all()
        assert not shots['mask'][:, :82].any()
        assert np.array_equal(shots['mask'][:, 82:], np.eye(96, dtype=bool))
        assert int(flips[index, 82:].sum()) == published[4]


def test_directed_phases_match_hashlib():
    """Every directed shot is a whole header, so hashlib can judge it."""
    inputs = SPEC.directed_inputs()
    flips = SPEC.phase(inputs)
    fields = bitcoin.from_registers(inputs)
    for index, block in enumerate(BLOCKS):
        for shot in (0, 1, 2, 49, 50, 81, 82, 100, 177):
            column = index * bitcoin.SHOTS_PER_BLOCK + shot
            if 2 <= shot < 50:
                continue  # The extranonce is inside the coinbase; hashlib would need the whole of it.
            nonce = int(fields['nonce'][column, 0]).to_bytes(4, 'big')
            mask = fields['mask'][column].astype('>u4').tobytes()
            assert flips[column] == flips_by_hashlib(block.header[:76] + nonce, mask), (block.height, shot)


# Random tests.


def random_chunk(chunk: int = 3, shots: int = 4096) -> dict:
    return sampling.random_inputs(SPEC, sampling.derive_seed(SPEC, 'ab' * 32, 'pin'), chunk, shots)


def test_random_tests_are_frozen():
    inputs = random_chunk()
    assert fingerprint(inputs) == RANDOM_INPUTS_SHA256
    assert phases_fingerprint(SPEC.phase(inputs)) == RANDOM_PHASES_SHA256


def test_random_inputs_depend_on_seed_and_chunk():
    base = fingerprint(random_chunk())
    assert fingerprint(random_chunk()) == base
    assert fingerprint(random_chunk(chunk=4)) != base
    other = sampling.random_inputs(SPEC, sampling.derive_seed(SPEC, 'ab' * 32, 'other'), 3, 4096)
    assert fingerprint(other) != base


def quotients(inputs: dict) -> tuple[list[int], list[int], list[int]]:
    """Per shot: the masked quotient q, the mantissa M, and the number of bits q can have."""
    fields = bitcoin.from_registers(inputs)
    masked = (bitcoin.block_hash(fields)[:, 5:] ^ fields['mask']).astype('>u4')
    exponent, mantissa = bitcoin.target(fields['bits'][:, 0])
    q = [int.from_bytes(masked[j].tobytes(), 'little') >> 8 * (int(exponent[j]) - 0x17) for j in range(len(masked))]
    return q, mantissa.tolist(), [96 - 8 * (int(e) - 0x17) for e in exponent]


def test_random_rows_put_the_hash_where_the_contract_says():
    inputs = random_chunk()
    flips = SPEC.phase(inputs)
    q, mantissa, width = quotients(inputs)
    for j in range(4096):
        row = (3 * 4096 + j) % 16
        if row <= 5:
            assert q[j] < mantissa[j] and flips[j]
        elif row <= 7:
            assert q[j] == mantissa[j] - 1 and flips[j]
        elif row <= 9:
            assert q[j] == mantissa[j] and not flips[j]
        elif row <= 11:
            assert mantissa[j] <= q[j] <= 0x7fffff and not flips[j]
        elif row <= 14:
            high = q[j] >> 23
            assert high and high & (high - 1) == 0 and q[j] < 1 << width[j]  # One bit set, from bit 23 up.
            assert q[j] & 0x7fffff < mantissa[j] and not flips[j]
        else:
            assert flips[j] == (q[j] < mantissa[j])
    assert int(flips.sum()) >= 2048  # Rows 0..7, plus the rare hit of a random mask.


def test_random_inputs_use_the_shot_index():
    rng = np.random.default_rng(13)
    raw = rng.integers(0, 256, size=(64, bitcoin.RANDOM_BYTES_PER_SHOT), dtype=np.uint8)
    at_0, at_8 = bitcoin.random_inputs(raw, 0), bitcoin.random_inputs(raw, 8)
    assert bitcoin.phase(at_0)[:6].all() and not bitcoin.phase(at_8)[:6].any()  # Rows 0..5 against 8..13.
    assert all(np.array_equal(at_0[name], at_8[name]) for name in at_0 if name != 'mask')


def test_random_inputs_are_in_the_allowed_range():
    inputs = sampling.random_inputs(SPEC, b'\x09' * 32, 0, 4096)
    fields = bitcoin.from_registers(inputs)
    exponent, mantissa = bitcoin.target(fields['bits'][:, 0])
    assert set(exponent.tolist()) == set(range(0x17, 0x21))
    assert {int(m).bit_length() for m in mantissa} == set(range(1, 24))
    assert all(300 < (exponent == e).sum() < 520 for e in range(0x17, 0x21))

    # The coinbase's last block ends a padded message of 64 k + L bytes, 6 <= L <= 55, 1 <= k <= 8.
    lengths = set()
    for last in fields['block'].astype('>u4'):
        data = last.tobytes()
        total = int.from_bytes(data[56:], 'big')
        assert total % 8 == 0
        k, length = divmod(total // 8, 64)
        assert 1 <= k <= 8 and 6 <= length <= 55
        assert data[length] == 0x80 and not any(data[length + 1:56])
        lengths.add(length)
    assert lengths == set(range(6, 56))


def test_random_inputs_reject_the_wrong_number_of_bytes():
    with pytest.raises(ValueError, match='199 random bytes per shot'):
        bitcoin.random_inputs(np.zeros((4, 100), dtype=np.uint8), 0)


def test_the_mask_alone_does_not_give_the_answer_away():
    """Each mask bit is balanced in the shots that must flip and in those that must not."""
    inputs = random_chunk()
    flips = SPEC.phase(inputs)
    for group in (inputs['mask'][:, flips], inputs['mask'][:, ~flips]):
        assert (np.abs(group.mean(axis=1) - 0.5) < 0.06).all()
