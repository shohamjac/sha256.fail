"""A correct circuit for `bitcoin-mining-v1`, for testing the verifier end to end.

It is plain, not good: every compression gets its own 768 qubits, the hash is computed in
full, the phase is applied, and then everything is run backwards. Options switch on
deliberate faults that the verifier must catch.

Like the baseline in submissions/example, this file does not use the verifier's reference
function, so a passing run is agreement between two separate implementations.
"""

from __future__ import annotations

import io
from typing import Callable

import kickmix as km

WORD = 32

# FIPS 180-4 section 4.2.2 and 5.3.3.
K = (
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
)
IV = (0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19)

# Words 8..15 of a block holding a 32-byte message, and 4..15 of the second block of an
# 80-byte message: the 0x80 byte, zeros, and the message length in bits.
PAD256 = (0x80000000, 0, 0, 0, 0, 0, 0, 256)
PAD640 = (0x80000000, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 640)

# (right rotations, right shift or None) of the four linear functions.
BIG_SIGMA0 = ((2, 13, 22), None)
BIG_SIGMA1 = ((6, 11, 25), None)
SMALL_SIGMA0 = ((7, 18), 3)
SMALL_SIGMA1 = ((17, 19), 10)


class OracleBuilder:
    """Builds the oracle. Registers are little-endian: offset k of a word is its bit k.

    Every step that changes qubits is recorded with its inverse in `self.undo`, so the
    whole computation can be run backwards after the phase is applied.

    Args:
        use_mask: False leaves the mask out, as if it were always zero.
        or_equal: True accepts a masked hash equal to the target, as Bitcoin does.
        compared_bits: How many bits of the hash, from bit 160 up, are compared. Fewer
            than 96 ignores the top ones.
        skip_phase: True never flips the phase.
    """

    def __init__(self, *, use_mask: bool = True, or_equal: bool = False, compared_bits: int = 96,
                 skip_phase: bool = False) -> None:
        self.use_mask, self.or_equal, self.compared_bits, self.skip_phase = use_mask, or_equal, compared_bits, skip_phase
        b = self.b = km.CircuitBuilder()
        self.extranonce = b.create_quantum_register(48, 'extranonce')
        self.nonce = b.create_quantum_register(32, 'nonce')
        self.midstate = b.create_classical_register(256, 'midstate')
        self.tail = b.create_classical_register(464, 'tail')
        self.version = b.create_classical_register(32, 'version')
        self.prev_hash = b.create_classical_register(256, 'prev_hash')
        self.time = b.create_classical_register(32, 'time')
        self.bits = b.create_classical_register(32, 'bits')
        self.mask = b.create_classical_register(96, 'mask')
        self.tmp = b.alloc_qubits(WORD)
        self.undo: list[Callable[[], None]] = []

    # Recorded steps.

    def copy(self, source: km.array, target: km.array) -> None:
        """`target ^= source`, where the source is qubits or classical bits."""
        self.b.cx(source, target)
        self.undo.append(lambda: self.b.cx(source, target))

    def set_constant(self, value: int, target: km.array) -> None:
        """`target ^= value`."""
        ones = [target[k] for k in range(len(target)) if (value >> k) & 1]
        if ones:
            self.b.x(ones)
            self.undo.append(lambda: self.b.x(ones))

    def add(self, offset: km.array | int, target: km.array) -> None:
        """`target += offset` modulo 2^32; the offset is qubits, classical bits or a constant."""
        self._add(offset, target, False)
        self.undo.append(lambda: self._add(offset, target, True))

    def add_linear(self, source: km.array, sigma, target: km.array) -> None:
        """`target += sigma(source)`."""
        self._add_linear(source, sigma, target, False)
        self.undo.append(lambda: self._add_linear(source, sigma, target, True))

    def add_ch(self, e: km.array, f: km.array, g: km.array, target: km.array) -> None:
        """`target += Ch(e, f, g)`."""
        self._add_ch(e, f, g, target, False)
        self.undo.append(lambda: self._add_ch(e, f, g, target, True))

    def add_maj(self, a: km.array, b: km.array, c: km.array, target: km.array) -> None:
        """`target += Maj(a, b, c)`."""
        self._add_maj(a, b, c, target, False)
        self.undo.append(lambda: self._add_maj(a, b, c, target, True))

    # What the recorded steps emit; `subtract` gives the inverse.

    def _add(self, offset, target, subtract: bool) -> None:
        (self.b.isub if subtract else self.b.iadd)(offset, target=target)

    def _xor_linear(self, source: km.array, sigma) -> None:
        rotations, shift = sigma
        for r in rotations:  # Bit i of a right rotation by r is bit i + r of the source.
            self.b.cx(km.array([source[(i + r) % WORD] for i in range(WORD)]), self.tmp)
        if shift is not None:  # A right shift drops the bits that would wrap around.
            self.b.cx(source[shift:], self.tmp[:WORD - shift])

    def _add_linear(self, source, sigma, target, subtract: bool) -> None:
        self._xor_linear(source, sigma)
        self._add(self.tmp, target, subtract)
        self._xor_linear(source, sigma)

    def _add_ch(self, e, f, g, target, subtract: bool) -> None:
        self.b.cx(g, f)  # Ch = g ^ (e & (f ^ g)).
        self.b.init_and(e, f, self.tmp)
        self.b.cx(g, self.tmp)
        self._add(self.tmp, target, subtract)
        self.b.cx(g, self.tmp)
        self.b.del_and(e, f, self.tmp)
        self.b.cx(g, f)

    def _add_maj(self, a, b, c, target, subtract: bool) -> None:
        self.b.cx(c, a)  # Maj = c ^ ((a ^ c) & (b ^ c)).
        self.b.cx(c, b)
        self.b.init_and(a, b, self.tmp)
        self.b.cx(c, self.tmp)
        self._add(self.tmp, target, subtract)
        self.b.cx(c, self.tmp)
        self.b.del_and(a, b, self.tmp)
        self.b.cx(c, b)
        self.b.cx(c, a)

    # SHA-256.

    def words(self, count: int) -> list[km.array]:
        qubits = self.b.alloc_qubits(count * WORD)
        return [qubits[WORD * j:WORD * (j + 1)] for j in range(count)]

    def compress(self, state: list[km.array], w: list[km.array], feed_forward: list) -> None:
        """Runs the 64 rounds on `state` with message words `w`, then adds `feed_forward`.

        `state` holds the starting chaining value and ends as the new one. `w` is expanded
        in place and left expanded. `feed_forward` is the starting chaining value again, as
        eight offsets for `add`.
        """
        s = list(state)
        for t in range(64):
            if t >= 16:  # W_t overwrites W_(t-16).
                target = w[t % 16]
                self.add_linear(w[(t - 15) % 16], SMALL_SIGMA0, target)
                self.add(w[(t - 7) % 16], target)
                self.add_linear(w[(t - 2) % 16], SMALL_SIGMA1, target)
            a, b, c, d, e, f, g, h = s
            self.add_linear(e, BIG_SIGMA1, h)
            self.add_ch(e, f, g, h)
            self.add(K[t], h)
            self.add(w[t % 16], h)  # h now holds T1.
            self.add(h, d)  # d now holds the new e.
            self.add_linear(a, BIG_SIGMA0, h)
            self.add_maj(a, b, c, h)  # h now holds the new a.
            s = [h, a, b, c, d, e, f, g]
        assert all(now is start for now, start in zip(s, state)), 'state registers did not line up'
        for word, offset in zip(state, feed_forward):
            self.add(offset, word)

    def classical_words(self, register: km.array) -> list[km.array]:
        return [register[WORD * j:WORD * (j + 1)] for j in range(len(register) // WORD)]

    def hash(self) -> list[km.array]:
        """Computes the block hash; returns the eight words holding it."""
        iv = list(IV)

        # Coinbase, last block: W_0 and the top half of W_1 are the extranonce.
        s1, w1 = self.words(8), self.words(16)
        midstate = self.classical_words(self.midstate)
        for word, source in zip(s1, midstate):
            self.copy(source, word)
        self.copy(self.extranonce[0:32], w1[0])
        self.copy(self.extranonce[32:48], w1[1][16:32])
        self.copy(self.tail[0:16], w1[1][0:16])
        for j in range(2, 16):
            self.copy(self.tail[16 + WORD * (j - 2):16 + WORD * (j - 1)], w1[j])
        self.compress(s1, w1, midstate)

        # Merkle root: the second hash of the coinbase.
        s2, w2 = self.words(8), self.words(16)
        for word, value in zip(s2, iv):
            self.set_constant(value, word)
        for j in range(8):
            self.copy(s1[j], w2[j])
            self.set_constant(PAD256[j], w2[8 + j])
        self.compress(s2, w2, iv)

        # Header, first block: version, previous block hash, and all but the last word of the root.
        s3, w3 = self.words(8), self.words(16)
        for word, value in zip(s3, iv):
            self.set_constant(value, word)
        self.copy(self.version, w3[0])
        for j, source in enumerate(self.classical_words(self.prev_hash)):
            self.copy(source, w3[1 + j])
        for j in range(7):
            self.copy(s2[j], w3[9 + j])
        self.compress(s3, w3, iv)

        # Header, second block, starting from the state after the first.
        s4, w4 = self.words(8), self.words(16)
        for word, source in zip(s4, s3):
            self.copy(source, word)
        self.copy(s2[7], w4[0])
        self.copy(self.time, w4[1])
        self.copy(self.bits, w4[2])
        self.copy(self.nonce, w4[3])
        for j, value in enumerate(PAD640):
            self.set_constant(value, w4[4 + j])
        self.compress(s4, w4, s3)

        # Block hash: the second hash of the header.
        s5, w5 = self.words(8), self.words(16)
        for word, value in zip(s5, iv):
            self.set_constant(value, word)
        for j in range(8):
            self.copy(s4[j], w5[j])
            self.set_constant(PAD256[j], w5[8 + j])
        self.compress(s5, w5, iv)
        return s5

    def target_bits(self) -> km.array:
        """Classical bits holding `M · 256^(e − 0x17)`: the target, from bit 160 of the hash up."""
        b = self.b
        exponent = self.bits[0:8]
        # Mantissa bit m, from the byte-swapped word the register holds.
        mantissa = km.array([self.bits[24 - 8 * (m // 8) + m % 8] for m in range(24)])
        not_exponent = b.alloc_bits(8)
        b.bit_store(not_exponent, True)
        b.cx(exponent, not_exponent)
        target = b.alloc_bits(96)
        b.bit_store(target, False)
        selected = b.alloc_bits(1)[0]
        for s in range(10):  # The exponent is 0x17 + s: the mantissa starts at byte s.
            b.bit_store(selected, True)
            for j in range(8):
                wrong = not_exponent[j] if ((0x17 + s) >> j) & 1 else exponent[j]
                b.bit_store(selected, False, control=wrong)
            b.push_condition(selected)
            b.cx(mantissa, target[8 * s:8 * s + 24])
            b.pop_condition()
        return target

    def build(self) -> km.Circuit:
        b = self.b
        digest = self.hash()
        if self.use_mask:
            for j in range(3):
                self.copy(self.mask[WORD * j:WORD * (j + 1)], digest[5 + j])

        # Bit p of the hash as an integer is in byte i = p // 8 of the digest, which is
        # bit 8 (3 - i % 4) + p % 8 of word i // 4.
        value = km.array([digest[(p // 8) // 4][8 * (3 - (p // 8) % 4) + p % 8] for p in range(160, 256)])
        n = self.compared_bits
        if not self.skip_phase:
            flag = b.alloc_qubits(1)[0]
            target = self.target_bits()
            b.flip_if_less_than(value[:n], target[:n], target=flag, or_equal=self.or_equal)
            b.z(flag)
            b.flip_if_less_than(value[:n], target[:n], target=flag, or_equal=self.or_equal)
            b.free(flag)

        for step in reversed(self.undo):
            step()
        b.free(self.tmp)
        return b.finish_circuit()


def build(**options) -> bytes:
    """The circuit as the bytes of a `.kmb` file."""
    buffer = io.BytesIO()
    OracleBuilder(**options).build().to_file(buffer, format='kmb')
    return buffer.getvalue()
