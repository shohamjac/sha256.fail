"""The problem `bitcoin-mining-v1`: its function, its real-block tests and its random tests.

The contract is docs/bitcoin-mining-v1.md. In short, the circuit is a phase oracle for

    inner1 = compress(midstate, extranonce ‖ tail)                      coinbase, last block
    root   = compress(IV, inner1 ‖ pad256)                              merkle root
    mid    = compress(IV, version ‖ prev_hash ‖ root[0:28])             header, first block
    inner2 = compress(mid, root[28:32] ‖ time ‖ bits ‖ nonce ‖ pad640)  header, second block
    hash   = compress(IV, inner2 ‖ pad256)                              block hash
    f      = int_le(hash with mask XORed into its last 12 bytes) < target(bits)

Inside this module a set of shots is held as `Fields`: unsigned 32-bit words, one row per
shot, big-endian over the bytes they stand for. `to_registers` and `from_registers` convert
between that and the register bits the simulator uses.

Random tests (see `random_inputs`): each shot takes `RANDOM_BYTES_PER_SHOT` bytes.

    bytes 0-5      extranonce            bytes 42-45    version
    bytes 6-9      nonce                 bytes 46-77    prev_hash
    bytes 10-41    midstate              bytes 78-81    time
    bytes 82-130   message bytes of the coinbase's last block; only the first L - 6 are used
    bytes 131-186  seven choices, each a little-endian 64-bit integer c_0 ... c_6
    bytes 187-198  fill, a little-endian 96-bit integer

    L = 6 + c_0 mod 50                   bytes of the coinbase in its last block
    k = 1 + c_1 mod 8                    the coinbase is 64 k + L bytes long
    e = 0x17 + c_2 mod 10                exponent
    n = 1 + c_3 mod 23                   bits in the mantissa
    M = 2^(n-1) + c_4 mod 2^(n-1)        mantissa

With the hash of the shot and `s = 8 (e - 0x17)`, the mask is chosen so that the masked
hash, from bit 160 up, is `q · 2^s + (fill mod 2^s)`. For shot `i` of the run:

    i mod 16 = 0..5     q = c_5 mod M
    i mod 16 = 6, 7     q = M - 1
    i mod 16 = 8, 9     q = M
    i mod 16 = 10, 11   q = M + c_5 mod (2^23 - M)
    i mod 16 = 12..14   q = (c_5 mod M) + 2^(23 + c_6 mod (73 - s))
    i mod 16 = 15       no q: the mask is the fill itself
"""

from __future__ import annotations

import numpy as np

from sha_verifier import bits, sha2
from sha_verifier.bitcoin_blocks import BLOCKS, Block

# (name, size, kind) of the registers, in the order a circuit declares them.
REGISTERS = (
    ('extranonce', 48, 'qubit'),
    ('nonce', 32, 'qubit'),
    ('midstate', 256, 'bit'),
    ('tail', 464, 'bit'),
    ('version', 32, 'bit'),
    ('prev_hash', 256, 'bit'),
    ('time', 32, 'bit'),
    ('bits', 32, 'bit'),
    ('mask', 96, 'bit'),
)

MIN_EXPONENT, MAX_EXPONENT = 0x17, 0x20
MAX_MANTISSA = 0x7fffff
RANDOM_BYTES_PER_SHOT = 199

# Shots of one real block in the directed tests: as mined, nonce + 1, one flip of each of
# the 80 search bits, and each of the 96 one-bit masks.
SHOTS_PER_BLOCK = 1 + 1 + 80 + 96

# Words by field name, each of shape `(n_shots, n_words)`: `block` is the coinbase's last
# block (16 words) and the other names are those of the registers.
Fields = dict[str, np.ndarray]

_P = sha2.SHA256
_IV = np.array(_P.iv, dtype=np.uint32)
_PAD256 = sha2.words_from_bytes(_P, sha2.pad(_P, bytes(32)))[0, 8:]   # Words 8..15 of a block holding a 32-byte message.
_PAD640 = sha2.words_from_bytes(_P, sha2.pad(_P, bytes(80)))[1, 4:]   # Words 4..15 of the second block of an 80-byte message.


def _words(data: bytes | np.ndarray, count: int) -> np.ndarray:
    """Bytes of shape `(n_shots, 4 * count)`, or one shot's bytes, as big-endian words `(n_shots, count)`."""
    raw = np.frombuffer(data, dtype=np.uint8) if isinstance(data, bytes) else np.asarray(data, dtype=np.uint8)
    return np.ascontiguousarray(raw.reshape(-1, 4 * count)).view('>u4').astype(np.uint32)


def _bytes(words: np.ndarray) -> np.ndarray:
    """Words of shape `(n_shots, n)` as their big-endian bytes, shape `(n_shots, 4 n)`."""
    return np.ascontiguousarray(words.astype('>u4')).view(np.uint8).reshape(len(words), -1)


def to_registers(fields: Fields) -> dict[str, np.ndarray]:
    """Register bits of `fields`, as the bit order section of the contract lays them out."""
    block = bits.words_to_bits(fields['block'])  # Offset 32 j + k is bit k of W_j.
    registers = {
        'extranonce': np.concatenate([block[0:32], block[48:64]]),
        'tail': np.concatenate([block[32:48], block[64:512]]),
    }
    for name in ('nonce', 'midstate', 'version', 'prev_hash', 'time', 'bits', 'mask'):
        registers[name] = bits.words_to_bits(fields[name])
    return {name: registers[name] for name, _, _ in REGISTERS}


def from_registers(registers: dict[str, np.ndarray]) -> Fields:
    """The inverse of `to_registers`."""
    extranonce, tail = registers['extranonce'], registers['tail']
    block = np.concatenate([extranonce[0:32], tail[0:16], extranonce[32:48], tail[16:464]])
    fields = {'block': bits.bits_to_words(block, 32)}
    for name in ('nonce', 'midstate', 'version', 'prev_hash', 'time', 'bits', 'mask'):
        fields[name] = bits.bits_to_words(registers[name], 32)
    return fields


def fields_from_bytes(*, midstate: bytes, extranonce: bytes, tail: bytes, version: bytes, prev_hash: bytes,
                      time: bytes, bits: bytes, nonce: bytes, mask: bytes = bytes(12)) -> Fields:
    """One shot from byte strings in message order, as the contract's test vectors give them."""
    lengths = {'midstate': 32, 'extranonce': 6, 'tail': 58, 'version': 4, 'prev_hash': 32, 'time': 4,
               'bits': 4, 'nonce': 4, 'mask': 12}
    given = dict(midstate=midstate, extranonce=extranonce, tail=tail, version=version, prev_hash=prev_hash,
                 time=time, bits=bits, nonce=nonce, mask=mask)
    for name, length in lengths.items():
        if len(given[name]) != length:
            raise ValueError(f'`{name}` must be {length} bytes, got {len(given[name])}.')
    fields = {'block': _words(extranonce + tail, 16)}
    for name in ('nonce', 'midstate', 'version', 'prev_hash', 'time', 'bits', 'mask'):
        fields[name] = _words(given[name], lengths[name] // 4)
    return fields


def block_hash(fields: Fields) -> np.ndarray:
    """The block hash of each shot before masking, as words `H_0 … H_7`, shape `(n_shots, 8)`."""
    n = len(fields['block'])
    pad256 = np.broadcast_to(_PAD256, (n, 8))
    pad640 = np.broadcast_to(_PAD640, (n, 12))
    inner1 = sha2.compress(_P, fields['midstate'], fields['block'])
    root = sha2.compress(_P, _IV, np.hstack([inner1, pad256]))
    mid = sha2.compress(_P, _IV, np.hstack([fields['version'], fields['prev_hash'], root[:, :7]]))
    inner2 = sha2.compress(_P, mid, np.hstack([root[:, 7:], fields['time'], fields['bits'], fields['nonce'], pad640]))
    return sha2.compress(_P, _IV, np.hstack([inner2, pad256]))


def target(bits_word: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Exponent and mantissa of each shot's `bits` word.

    Raises:
        ValueError: A target is outside the range the problem allows.
    """
    word = np.asarray(bits_word, dtype=np.uint32)
    exponent = word & 0xff
    mantissa = (word >> 24) | ((word >> 8) & 0xff00) | ((word << 8) & 0xff0000)
    if ((exponent < MIN_EXPONENT) | (exponent > MAX_EXPONENT) | (mantissa < 1) | (mantissa > MAX_MANTISSA)).any():
        raise ValueError('A target is outside the allowed range of exponents and mantissas.')
    return exponent, mantissa


def _top_bytes(fields: Fields) -> np.ndarray:
    """Bytes 20..31 of each shot's block hash before masking, shape `(n_shots, 12)`.

    Read least significant byte first they are bits 160..255 of the hash as an integer.
    """
    return _bytes(block_hash(fields)[:, 5:])


def phase(registers: dict[str, np.ndarray]) -> np.ndarray:
    """For each shot, whether the masked hash is below the target: the phase must flip."""
    fields = from_registers(registers)
    top = _top_bytes(fields) ^ _bytes(fields['mask'])
    exponent, mantissa = target(fields['bits'][:, 0])
    # With s = e - 0x17, the quotient q = floor(v / 256^(e - 3)) is `top` from byte s up.
    # It is below the mantissa, which fits three bytes, exactly when its three low bytes
    # are and every byte above them is zero.
    s = (exponent - MIN_EXPONENT).astype(np.intp)
    low = np.take_along_axis(top, s[:, None] + np.arange(3), axis=1).astype(np.uint32)
    low = low[:, 0] | (low[:, 1] << 8) | (low[:, 2] << 16)
    above = np.arange(12)[None, :] >= s[:, None] + 3
    return (low < mantissa) & ~((top != 0) & above).any(axis=1)


def block_fields(block: Block) -> Fields:
    """A real block as one shot with a zero mask, as "From a real block to inputs" describes.

    Raises:
        ValueError: The coinbase's last block does not hold 6 to 55 of its bytes.
    """
    if not 6 <= len(block.coinbase) % 64 <= 55:
        raise ValueError(f'The coinbase of block {block.height} does not fit: its last block '
                         f'holds {len(block.coinbase) % 64} bytes.')
    blocks = sha2.words_from_bytes(_P, sha2.pad(_P, block.coinbase))
    midstate = _IV
    for words in blocks[:-1]:
        midstate = sha2.compress(_P, midstate, words[None, :])[0]
    header = block.header
    return {
        'block': blocks[-1:],
        'midstate': midstate[None, :],
        'version': _words(header[0:4], 1),
        'prev_hash': _words(header[4:36], 8),
        'time': _words(header[68:72], 1),
        'bits': _words(header[72:76], 1),
        'nonce': _words(header[76:80], 1),
        'mask': np.zeros((1, 3), dtype=np.uint32),
    }


def _block_shots(block: Block) -> dict[str, np.ndarray]:
    """The `SHOTS_PER_BLOCK` directed shots of one block, as register bits."""
    fields = block_fields(block)
    shots = {name: np.repeat(column, SHOTS_PER_BLOCK, axis=1) for name, column in to_registers(fields).items()}

    # Shot 1: the nonce, as the number Bitcoin shows, increased by one.
    bumped = (fields['nonce'].byteswap() + np.uint32(1)).byteswap()
    shots['nonce'][:, 1] = bits.words_to_bits(bumped)[:, 0]

    # Shots 2..81: one bit of the search register flipped, extranonce first.
    shot = 2
    for name in ('extranonce', 'nonce'):
        for offset in range(len(shots[name])):
            shots[name][offset, shot] ^= True
            shot += 1

    # Shots 82..177: one bit of the mask set.
    for offset in range(96):
        shots['mask'][offset, shot] = True
        shot += 1
    assert shot == SHOTS_PER_BLOCK
    return shots


def directed_inputs() -> dict[str, np.ndarray]:
    """The directed tests: `SHOTS_PER_BLOCK` shots for each real block. The order is part of the contract."""
    per_block = [_block_shots(block) for block in BLOCKS]
    return {name: np.concatenate([shots[name] for shots in per_block], axis=1) for name, _, _ in REGISTERS}


def random_inputs(raw: np.ndarray, first_index: int) -> dict[str, np.ndarray]:
    """Random test inputs from the shots' random bytes; the module docstring gives the rules.

    Args:
        raw: Random bytes, shape `(n_shots, RANDOM_BYTES_PER_SHOT)`.
        first_index: Index in the run of the first of these shots.
    """
    raw = np.asarray(raw, dtype=np.uint8)
    n = len(raw)
    if raw.shape != (n, RANDOM_BYTES_PER_SHOT):
        raise ValueError(f'Expected {RANDOM_BYTES_PER_SHOT} random bytes per shot, got shape {raw.shape}.')
    choice = np.ascontiguousarray(raw[:, 131:187]).view('<u8').astype(np.uint64)
    last_bytes = 6 + choice[:, 0] % np.uint64(50)
    coinbase_bytes = 64 * (1 + choice[:, 1] % np.uint64(8)) + last_bytes
    exponent = MIN_EXPONENT + choice[:, 2] % np.uint64(MAX_EXPONENT - MIN_EXPONENT + 1)
    half = np.uint64(1) << (choice[:, 3] % np.uint64(23))  # 2^(n-1) for a mantissa of n bits.
    mantissa = half + choice[:, 4] % half

    # The coinbase's last block: extranonce, message bytes, then SHA-256 padding.
    columns = np.arange(64)[None, :]
    last = np.zeros((n, 64), dtype=np.uint8)
    last[:, 0:6] = raw[:, 0:6]
    last[:, 6:55] = raw[:, 82:131]
    last[columns >= last_bytes[:, None]] = 0
    last[np.arange(n), last_bytes.astype(np.intp)] = 0x80
    length_bits = 8 * coinbase_bytes  # At most 4,536, so it fits the last two bytes.
    last[:, 62], last[:, 63] = length_bits >> np.uint64(8), length_bits & np.uint64(0xff)

    m = mantissa.astype(np.uint32)
    fields = {
        'block': _words(last, 16),
        'nonce': _words(raw[:, 6:10], 1),
        'midstate': _words(raw[:, 10:42], 8),
        'version': _words(raw[:, 42:46], 1),
        'prev_hash': _words(raw[:, 46:78], 8),
        'time': _words(raw[:, 78:82], 1),
        # Header bytes 72..75 are the mantissa, least significant byte first, then the exponent.
        'bits': (((m & 0xff) << 24) | ((m >> 8 & 0xff) << 16) | ((m >> 16) << 8) | exponent.astype(np.uint32))[:, None],
        'mask': np.zeros((n, 3), dtype=np.uint32),
    }

    top = _top_bytes(fields)
    masks = np.zeros((n, 12), dtype=np.uint8)
    for j in range(n):  # 96-bit integers: plain Python is the clearest way to get them right.
        row = (first_index + j) % 16
        fill = int.from_bytes(raw[j, 187:199].tobytes(), 'little')
        if row == 15:
            mask = fill
        else:
            mant, c5, c6 = int(mantissa[j]), int(choice[j, 5]), int(choice[j, 6])
            shift = 8 * (int(exponent[j]) - MIN_EXPONENT)
            if row <= 5:
                q = c5 % mant
            elif row <= 7:
                q = mant - 1
            elif row <= 9:
                q = mant
            elif row <= 11:
                q = mant + c5 % (2**23 - mant)
            else:
                q = (c5 % mant) | (1 << (23 + c6 % (73 - shift)))
            wanted = (q << shift) | (fill & ((1 << shift) - 1))
            mask = int.from_bytes(top[j].tobytes(), 'little') ^ wanted
        masks[j] = np.frombuffer(mask.to_bytes(12, 'little'), dtype=np.uint8)
    fields['mask'] = _words(masks, 3)
    return to_registers(fields)
