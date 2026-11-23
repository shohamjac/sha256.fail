"""Builds the baseline circuit for the problem `bitcoin-mining-v1`.

    |extranonce, nonce>  ->  (-1)^f |extranonce, nonce>

with f = 1 when the masked block hash is below the target. The other seven registers are
classical bits. The contract is sha256_verifier/docs/bitcoin-mining-v1.md.

A plain, readable construction, meant as a starting point rather than a good score:

- The five SHA-256 compressions are each built the way the baseline for
  `sha256-compress-v1` builds one (submissions/example): the state is updated in place
  over 64 rounds, the message schedule is expanded in place over the block and then
  rewound, and every addition is Kickmix's adder, which clears its carries by measurement.
- Each compression has its own 256-qubit state register. All five share one 512-qubit
  block register: a block is XORed in before its compression and XORed out again after
  the schedule is rewound.
- Classical inputs are treated like quantum ones. A classical word is XORed into qubits
  and from then on handled as any other word.
- The mask is XORed into the hash, a comparison against the target sets one qubit, a Z on
  that qubit is the phase, and the comparison is undone.
- Then everything is run backwards. Every step records its inverse as it is emitted.

This file uses only Kickmix, numpy, the standard library and zstd (standard library from
Python 3.14, `backports.zstd` before that) to compress its output. It deliberately does not
import the verifier: `check` compares the circuit against `hashlib` instead, so the
circuit and the verifier's reference function are written and checked independently.

Usage, from this directory:

    uv run --project ../../sha256_verifier python build.py
"""

from __future__ import annotations

import hashlib
import io
import pathlib
from typing import Callable

import kickmix as km
import numpy as np

try:
    from compression import zstd  # Python 3.14 and later.
except ImportError:
    from backports import zstd

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

# The SHA-256 padding of a 32-byte message, as words 8..15 of its block, and of an 80-byte
# message, as words 4..15 of its second block: the 0x80 byte, zeros, the length in bits.
PAD256 = (0x80000000, 0, 0, 0, 0, 0, 0, 256)
PAD640 = (0x80000000, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 640)

# (right rotations, right shift or None) of the four linear functions.
BIG_SIGMA0 = ((2, 13, 22), None)
BIG_SIGMA1 = ((6, 11, 25), None)
SMALL_SIGMA0 = ((7, 18), 3)
SMALL_SIGMA1 = ((17, 19), 10)

MIN_EXPONENT, MAX_EXPONENT = 0x17, 0x20


class BitcoinOracleBuilder:
    """Emits the oracle into a `km.CircuitBuilder`.

    Registers are little-endian: offset k of a word register is bit k of the word.

    Every step that changes qubits goes through `step`, `xor` or `xor_constant`, which
    record the step's inverse in `self.undo`. Running that list backwards uncomputes
    everything.
    """

    # Bitcoin accepts a hash equal to the target; the problem does not. See the contract.
    OR_EQUAL = False

    def __init__(self) -> None:
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
        self.w = self.words(b.alloc_qubits(16 * WORD))  # The message block, shared by all compressions.
        self.tmp = b.alloc_qubits(WORD)
        self.undo: list[Callable[[], None]] = []

    @staticmethod
    def words(register: km.array) -> list[km.array]:
        return [register[WORD * j:WORD * (j + 1)] for j in range(len(register) // WORD)]

    # Recorded steps.

    def xor(self, source: km.array, target: km.array) -> None:
        """`target ^= source`. The source is qubits or classical bits. Its own inverse."""
        self.b.cx(source, target)
        self.undo.append(lambda: self.b.cx(source, target))

    def xor_constant(self, value: int, target: km.array) -> None:
        """`target ^= value`. Its own inverse."""
        ones = [target[k] for k in range(len(target)) if (value >> k) & 1]
        if ones:
            self.b.x(ones)
            self.undo.append(lambda: self.b.x(ones))

    def step(self, emit: Callable[..., None], *operands, subtract: bool = False) -> None:
        """Emits an addition step and records the matching subtraction, or the reverse."""
        emit(*operands, subtract)
        self.undo.append(lambda: emit(*operands, not subtract))

    # Addition steps: `target += something`, or `-=` when `subtract` is set.

    def add(self, offset: km.array | int, target: km.array, subtract: bool) -> None:
        """`target += offset` modulo 2^32. Every addition in the circuit goes through here."""
        (self.b.isub if subtract else self.b.iadd)(offset, target=target)

    def xor_linear(self, source: km.array, sigma: tuple[tuple[int, ...], int | None]) -> None:
        """`tmp ^= sigma(source)`. Applying it twice restores `tmp`."""
        rotations, shift = sigma
        for r in rotations:  # Bit i of a right rotation by r is bit i + r of the source.
            self.b.cx(km.array([source[(i + r) % WORD] for i in range(WORD)]), self.tmp)
        if shift is not None:  # A right shift drops the bits that would wrap around.
            self.b.cx(source[shift:], self.tmp[:WORD - shift])

    def add_linear(self, source: km.array, sigma, target: km.array, subtract: bool) -> None:
        """`target += sigma(source)`."""
        self.xor_linear(source, sigma)
        self.add(self.tmp, target, subtract)
        self.xor_linear(source, sigma)

    def add_ch(self, e: km.array, f: km.array, g: km.array, target: km.array, subtract: bool) -> None:
        """`target += Ch(e, f, g)`, using `Ch = g ^ (e & (f ^ g))`: one AND per bit."""
        self.b.cx(g, f)
        self.b.init_and(e, f, self.tmp)
        self.b.cx(g, self.tmp)
        self.add(self.tmp, target, subtract)
        self.b.cx(g, self.tmp)
        self.b.del_and(e, f, self.tmp)  # Measured away; costs no Toffoli.
        self.b.cx(g, f)

    def add_maj(self, a: km.array, b: km.array, c: km.array, target: km.array, subtract: bool) -> None:
        """`target += Maj(a, b, c)`, using `Maj = c ^ ((a ^ c) & (b ^ c))`: one AND per bit."""
        self.b.cx(c, a)
        self.b.cx(c, b)
        self.b.init_and(a, b, self.tmp)
        self.b.cx(c, self.tmp)
        self.add(self.tmp, target, subtract)
        self.b.cx(c, self.tmp)
        self.b.del_and(a, b, self.tmp)
        self.b.cx(c, b)
        self.b.cx(c, a)

    # SHA-256.

    def round(self, t: int, state: list[km.array]) -> list[km.array]:
        """One round in place; returns the registers now holding a..h.

        With T1 = h + Sigma1(e) + Ch(e,f,g) + K_t + W_t and T2 = Sigma0(a) + Maj(a,b,c), the
        new state is (T1 + T2, a, b, c, d + T1, e, f, g). So h and d are updated and the
        eight registers are relabelled; nothing else moves.
        """
        a, b, c, d, e, f, g, h = state
        self.step(self.add_linear, e, BIG_SIGMA1, h)
        self.step(self.add_ch, e, f, g, h)
        self.step(self.add, K[t], h)
        self.step(self.add, self.w[t % 16], h)  # h now holds T1.
        self.step(self.add, h, d)  # d now holds the new e.
        self.step(self.add_linear, a, BIG_SIGMA0, h)
        self.step(self.add_maj, a, b, c, h)  # h now holds the new a.
        return [h, a, b, c, d, e, f, g]

    def schedule(self, t: int, *, rewind: bool = False) -> None:
        """Turns W_(t-16) into W_t in place, or back again.

        W_t = W_(t-16) + sigma0(W_(t-15)) + W_(t-7) + sigma1(W_(t-2)); word W_s is `w[s % 16]`.
        """
        target = self.w[t % 16]
        steps = [
            lambda: self.step(self.add_linear, self.w[(t - 15) % 16], SMALL_SIGMA0, target, subtract=rewind),
            lambda: self.step(self.add, self.w[(t - 7) % 16], target, subtract=rewind),
            lambda: self.step(self.add_linear, self.w[(t - 2) % 16], SMALL_SIGMA1, target, subtract=rewind),
        ]
        for emit in (reversed(steps) if rewind else steps):
            emit()

    def compress(self, state: list[km.array], load_block: Callable[[], None], feed_forward: list, *,
                 keep_block: bool = False) -> None:
        """`state = compress(state, block)`.

        Args:
            state: Holds the starting chaining value; ends as the new one.
            load_block: XORs the block into `self.w`, which is all zero before. It is called
                a second time, after the schedule is rewound, to clear `self.w` again.
            feed_forward: The starting chaining value again, as eight offsets for `add`:
                constants, classical bits or qubits.
            keep_block: Leave the block loaded and its schedule expanded.
        """
        load_block()
        registers = list(state)
        for t in range(64):
            if t >= 16:
                self.schedule(t)
            registers = self.round(t, registers)
        assert all(now is start for now, start in zip(registers, state)), 'state registers did not line up'
        for word, offset in zip(state, feed_forward):
            self.step(self.add, offset, word)
        if not keep_block:
            for t in reversed(range(16, 64)):
                self.schedule(t, rewind=True)
            load_block()

    def new_state(self, start: list) -> list[km.array]:
        """A fresh 256-qubit state register holding `start`: constants, classical bits or qubits."""
        state = self.words(self.b.alloc_qubits(8 * WORD))
        for word, value in zip(state, start):
            if isinstance(value, int):
                self.xor_constant(value, word)
            else:
                self.xor(value, word)
        return state

    # The oracle.

    def hash(self) -> list[km.array]:
        """Computes the block hash; returns the eight words holding it.

        The last compression leaves its block loaded: unloading it would be the first thing
        the backward pass undoes.
        """
        w = self.w
        iv = list(IV)

        def coinbase_block() -> None:  # extranonce ‖ tail. W_0 and the top half of W_1 are the extranonce.
            self.xor(self.extranonce[0:32], w[0])
            self.xor(self.extranonce[32:48], w[1][16:32])
            self.xor(self.tail[0:16], w[1][0:16])
            for j in range(2, 16):
                self.xor(self.tail[16 + WORD * (j - 2):16 + WORD * (j - 1)], w[j])

        midstate = self.words(self.midstate)
        inner1 = self.new_state(midstate)
        self.compress(inner1, coinbase_block, midstate)

        def digest_block(digest: list[km.array]) -> Callable[[], None]:  # A 32-byte digest and its padding.
            def load() -> None:
                for j in range(8):
                    self.xor(digest[j], w[j])
                    self.xor_constant(PAD256[j], w[8 + j])
            return load

        root = self.new_state(iv)
        self.compress(root, digest_block(inner1), iv)

        def header_block_1() -> None:  # version ‖ prev_hash ‖ root[0:28].
            self.xor(self.version, w[0])
            for j, word in enumerate(self.words(self.prev_hash)):
                self.xor(word, w[1 + j])
            for j in range(7):
                self.xor(root[j], w[9 + j])

        mid = self.new_state(iv)
        self.compress(mid, header_block_1, iv)

        def header_block_2() -> None:  # root[28:32] ‖ time ‖ bits ‖ nonce ‖ pad640.
            self.xor(root[7], w[0])
            self.xor(self.time, w[1])
            self.xor(self.bits, w[2])
            self.xor(self.nonce, w[3])
            for j, value in enumerate(PAD640):
                self.xor_constant(value, w[4 + j])

        inner2 = self.new_state(mid)
        self.compress(inner2, header_block_2, mid)

        digest = self.new_state(iv)
        self.compress(digest, digest_block(inner2), iv, keep_block=True)
        return digest

    def apply_mask(self, digest: list[km.array]) -> None:
        """XORs the mask into H_5, H_6 and H_7."""
        for j in range(3):
            self.xor(self.mask[WORD * j:WORD * (j + 1)], digest[5 + j])

    def compared(self, digest: list[km.array]) -> km.array:
        """Bits 160..255 of the hash read as an integer, least significant first.

        Bit p of that integer is in byte i = p // 8 of the digest, which is bit
        8 (3 - i % 4) + p % 8 of word i // 4.
        """
        return km.array([digest[(p // 8) // 4][8 * (3 - (p // 8) % 4) + p % 8] for p in range(160, 256)])

    def target(self) -> km.array:
        """96 classical bits holding the target from bit 160 up: `M · 256^(e − 0x17)`.

        Computed from the `bits` register with classical operations only, which cost nothing.
        """
        b = self.b
        exponent = self.bits[0:8]
        # Mantissa bit m, out of the byte-swapped word the register holds.
        mantissa = km.array([self.bits[24 - 8 * (m // 8) + m % 8] for m in range(24)])
        not_exponent = b.alloc_bits(8)
        b.bit_store(not_exponent, True)
        b.cx(exponent, not_exponent)
        target = b.alloc_bits(96)
        b.bit_store(target, False)
        selected = b.alloc_bits(1)[0]
        for s in range(MAX_EXPONENT - MIN_EXPONENT + 1):  # Exponent 0x17 + s: the mantissa starts at byte s.
            b.bit_store(selected, True)
            for j in range(8):
                wrong = not_exponent[j] if ((MIN_EXPONENT + s) >> j) & 1 else exponent[j]
                b.bit_store(selected, False, control=wrong)
            b.push_condition(selected)
            b.cx(mantissa, target[8 * s:8 * s + 24])
            b.pop_condition()
        return target

    def phase(self, digest: list[km.array]) -> None:
        """Flips the phase when the masked hash is below the target."""
        b = self.b
        value, target = self.compared(digest), self.target()
        flag = b.alloc_qubits(1)[0]
        b.flip_if_less_than(value, target[:len(value)], target=flag, or_equal=self.OR_EQUAL)
        b.z(flag)
        b.flip_if_less_than(value, target[:len(value)], target=flag, or_equal=self.OR_EQUAL)
        b.free(flag)

    def build(self) -> km.Circuit:
        digest = self.hash()
        self.apply_mask(digest)
        self.phase(digest)
        for inverse in reversed(self.undo):
            inverse()
        return self.b.finish_circuit()


# Checking the circuit against hashlib.


def sha256d(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def compress(state: tuple[int, ...], block: bytes) -> tuple[int, ...]:
    """Plain SHA-256 compression, used only to get the midstate of a test coinbase."""
    mask = 0xffffffff
    rotr = lambda x, n: ((x >> n) | (x << (32 - n))) & mask
    w = [int.from_bytes(block[4 * i:4 * i + 4], 'big') for i in range(16)]
    for t in range(16, 64):
        s0 = rotr(w[t - 15], 7) ^ rotr(w[t - 15], 18) ^ (w[t - 15] >> 3)
        s1 = rotr(w[t - 2], 17) ^ rotr(w[t - 2], 19) ^ (w[t - 2] >> 10)
        w.append((w[t - 16] + s0 + w[t - 7] + s1) & mask)
    a, b, c, d, e, f, g, h = state
    for t in range(64):
        t1 = (h + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + K[t] + w[t]) & mask
        t2 = ((rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) & mask
        a, b, c, d, e, f, g, h = (t1 + t2) & mask, a, b, c, (d + t1) & mask, e, f, g
    return tuple((x + y) & mask for x, y in zip(state, (a, b, c, d, e, f, g, h)))


def byte_bits(data: bytes) -> list[bool]:
    """Bytes of whole big-endian words as register bits: bit b of byte i is at 32 (i // 4) + 8 (3 - i % 4) + b."""
    out = [False] * (8 * len(data))
    for i, byte in enumerate(data):
        for b in range(8):
            out[32 * (i // 4) + 8 * (3 - i % 4) + b] = bool((byte >> b) & 1)
    return out


def shot_inputs(coinbase: bytes, header: bytes, mask: bytes) -> dict[str, list[bool]]:
    """Register bits for a block given by its coinbase and its 80-byte header."""
    assert 6 <= len(coinbase) % 64 <= 55, 'the coinbase does not fit the problem'
    padded = coinbase + b'\x80' + bytes(55 - len(coinbase) % 64) + (8 * len(coinbase)).to_bytes(8, 'big')
    state = IV
    for start in range(0, len(padded) - 64, 64):
        state = compress(state, padded[start:start + 64])
    last = byte_bits(padded[-64:])
    return {
        'extranonce': last[0:32] + last[48:64],
        'nonce': byte_bits(header[76:80]),
        'midstate': byte_bits(b''.join(word.to_bytes(4, 'big') for word in state)),
        'tail': last[32:48] + last[64:512],
        'version': byte_bits(header[0:4]),
        'prev_hash': byte_bits(header[4:36]),
        'time': byte_bits(header[68:72]),
        'bits': byte_bits(header[72:76]),
        'mask': byte_bits(mask),
    }


def expected_flip(header: bytes, mask: bytes) -> bool:
    """The problem's function, with hashlib and integers."""
    digest = sha256d(header)
    masked = digest[:20] + bytes(x ^ y for x, y in zip(digest[20:], mask))
    target = int.from_bytes(header[72:75], 'little') << 8 * (header[75] - 3)
    return int.from_bytes(masked, 'little') < target


def check(circuit: km.Circuit, shots: int = 1024) -> None:
    """Checks the circuit against `hashlib` on made-up blocks, with masks that aim near the target."""
    registers = circuit.register_data
    arrays = {name: km.array(list(registers[name])) for name in registers}
    search = set(registers['extranonce']) | set(registers['nonce'])
    scratch = km.array([km.q(i) for i in range(circuit.num_qubits) if km.q(i) not in search])

    rng = np.random.default_rng(2026)
    batch = 256
    sim = km.Simulator(batch_size=batch, debug_print=False, seed=1)
    flips = 0
    for start in range(0, shots, batch):
        inputs, expected = [], []
        for shot in range(start, start + batch):
            coinbase = rng.bytes(64 * int(rng.integers(1, 9)) + 6 + shot % 50)
            exponent = MIN_EXPONENT + shot % 10
            mantissa = int(rng.integers(1, 0x800000))
            header = (rng.bytes(36) + sha256d(coinbase) + rng.bytes(4) + mantissa.to_bytes(3, 'little')
                      + bytes([exponent]) + rng.bytes(4))
            # Aim the masked hash just below, at, and just above the target, and anywhere.
            top = int.from_bytes(sha256d(header)[20:], 'little')
            shift = 8 * (exponent - MIN_EXPONENT)
            quotient = [mantissa - 1, mantissa, int(rng.integers(0, mantissa)), mantissa - 1 + (1 << 23), None][shot % 5]
            if quotient is None:
                mask = rng.bytes(12)
            else:
                low = int.from_bytes(rng.bytes(12), 'little') & ((1 << shift) - 1)
                mask = (top ^ (quotient << shift | low)).to_bytes(12, 'little')
            inputs.append(shot_inputs(coinbase, header, mask))
            expected.append(expected_flip(header, mask))

        sim.clear_for_shot()
        columns = {name: np.array([shot[name] for shot in inputs], dtype=bool).T for name in arrays}
        for name, array in arrays.items():
            sim.write_across_shots(array, columns[name])
        sim.do(circuit)
        flipped = np.asarray(sim.read_phase_flipped_across_shots(), dtype=bool)
        assert flipped.tolist() == expected, 'phase differs from hashlib'
        for name in ('extranonce', 'nonce'):
            assert np.array_equal(sim.read_across_shots(arrays[name]), columns[name]), f'{name} was not restored'
        assert not sim.read_across_shots(scratch).any(), 'scratch is not clean'
        flips += sum(expected)
    assert shots // 4 < flips < 3 * shots // 4, 'the check must see both answers often'


def main(builder: type[BitcoinOracleBuilder] = BitcoinOracleBuilder, script: str = __file__) -> None:
    """Builds with `builder`, checks against hashlib, and writes circuit.kmb.zst next to `script`."""
    circuit = builder().build()
    check(circuit)
    buffer = io.BytesIO()
    circuit.to_file(buffer, format='kmb')
    path = pathlib.Path(script).with_name('circuit.kmb.zst')
    path.write_bytes(zstd.compress(buffer.getvalue(), level=19))
    stats = circuit.operation_statistics()
    print(f'Wrote {path.name}: {circuit.num_qubits} qubits, {stats.num_toffoli_like} Toffolis, '
          f'{len(circuit)} operations, {len(buffer.getvalue())} bytes ({path.stat().st_size} compressed). '
          'Matches hashlib on 1024 made-up blocks.')


if __name__ == '__main__':
    main()
