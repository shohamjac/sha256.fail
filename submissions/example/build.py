"""Builds the baseline circuit for the problem `sha256-compress-v1`.

    block (512 qubits, unchanged), digest (256 qubits, starts 0)  ->  digest = compress(IV, block)

A plain, readable construction, meant as a starting point rather than a good score:

- The working state lives in the `digest` register itself. It is set to the initial hash
  value, run through the 64 rounds in place, and has the initial hash value added back.
  Each round is reversible given its message word, so the rounds are never uncomputed.
- The message schedule is expanded in place over `block`: word W_t overwrites W_(t-16).
  After the last round the schedule is run backwards to restore the block.
- Every addition is Kickmix's adder, which clears its carries by measurement.
- One 32-qubit temporary holds whichever of Sigma, Ch or Maj is being added.

This file uses only Kickmix, numpy and the standard library. It deliberately does not
import the verifier: `check` compares the circuit against `hashlib` instead, so the
circuit and the verifier's reference function are written and checked independently.

Usage, from this directory:

    uv run --project ../../sha256_verifier python build.py
"""

from __future__ import annotations

import hashlib
import pathlib

import kickmix as km
import numpy as np

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

# (right rotations, right shift or None) of the four linear functions.
BIG_SIGMA0 = ((2, 13, 22), None)
BIG_SIGMA1 = ((6, 11, 25), None)
SMALL_SIGMA0 = ((7, 18), 3)
SMALL_SIGMA1 = ((17, 19), 10)


class Sha256Builder:
    """Emits SHA-256 building blocks into a `km.CircuitBuilder`.

    Registers are little-endian: offset k of a word register is bit k of the word.
    """

    def __init__(self) -> None:
        self.b = km.CircuitBuilder()
        block = self.b.create_quantum_register(16 * WORD, 'block')
        digest = self.b.create_quantum_register(8 * WORD, 'digest')
        self.w = [block[WORD * j:WORD * (j + 1)] for j in range(16)]
        self.h = [digest[WORD * j:WORD * (j + 1)] for j in range(8)]
        self.tmp = self.b.alloc_qubits(WORD)

    def xor_linear(self, source: km.array, sigma: tuple[tuple[int, ...], int | None]) -> None:
        """`tmp ^= sigma(source)`. Applying it twice restores `tmp`."""
        rotations, shift = sigma
        for r in rotations:  # Bit i of a right rotation by r is bit i + r of the source.
            self.b.cx(km.array([source[(i + r) % WORD] for i in range(WORD)]), self.tmp)
        if shift is not None:  # A right shift drops the bits that would wrap around.
            self.b.cx(source[shift:], self.tmp[:WORD - shift])

    def add_linear(self, source: km.array, sigma, target: km.array, *, subtract: bool = False) -> None:
        """`target += sigma(source)`, or `-=`."""
        self.xor_linear(source, sigma)
        (self.b.isub if subtract else self.b.iadd)(self.tmp, target=target)
        self.xor_linear(source, sigma)

    def add_ch(self, e: km.array, f: km.array, g: km.array, target: km.array) -> None:
        """`target += Ch(e, f, g)`, using `Ch = g ^ (e & (f ^ g))`: one AND per bit."""
        self.b.cx(g, f)
        self.b.init_and(e, f, self.tmp)
        self.b.cx(g, self.tmp)
        self.b.iadd(self.tmp, target=target)
        self.b.cx(g, self.tmp)
        self.b.del_and(e, f, self.tmp)  # Measured away; costs no Toffoli.
        self.b.cx(g, f)

    def add_maj(self, a: km.array, b: km.array, c: km.array, target: km.array) -> None:
        """`target += Maj(a, b, c)`, using `Maj = c ^ ((a ^ c) & (b ^ c))`: one AND per bit."""
        self.b.cx(c, a)
        self.b.cx(c, b)
        self.b.init_and(a, b, self.tmp)
        self.b.cx(c, self.tmp)
        self.b.iadd(self.tmp, target=target)
        self.b.cx(c, self.tmp)
        self.b.del_and(a, b, self.tmp)
        self.b.cx(c, b)
        self.b.cx(c, a)

    def round(self, t: int, state: list[km.array]) -> list[km.array]:
        """One round in place; returns the registers now holding a..h.

        With T1 = h + Sigma1(e) + Ch(e,f,g) + K_t + W_t and T2 = Sigma0(a) + Maj(a,b,c), the
        new state is (T1 + T2, a, b, c, d + T1, e, f, g). So h and d are updated and the
        eight registers are relabelled; nothing else moves.
        """
        a, b, c, d, e, f, g, h = state
        self.add_linear(e, BIG_SIGMA1, h)
        self.add_ch(e, f, g, h)
        self.b.iadd(K[t], target=h)
        self.b.iadd(self.w[t % 16], target=h)  # h now holds T1.
        self.b.iadd(h, target=d)  # d now holds the new e.
        self.add_linear(a, BIG_SIGMA0, h)
        self.add_maj(a, b, c, h)  # h now holds the new a.
        return [h, a, b, c, d, e, f, g]

    def schedule(self, t: int, *, undo: bool = False) -> None:
        """Turns W_(t-16) into W_t in place, or back again.

        W_t = W_(t-16) + sigma0(W_(t-15)) + W_(t-7) + sigma1(W_(t-2)); word W_s is `w[s % 16]`.
        """
        target = self.w[t % 16]
        steps = [
            lambda: self.add_linear(self.w[(t - 15) % 16], SMALL_SIGMA0, target, subtract=undo),
            lambda: (self.b.isub if undo else self.b.iadd)(self.w[(t - 7) % 16], target=target),
            lambda: self.add_linear(self.w[(t - 2) % 16], SMALL_SIGMA1, target, subtract=undo),
        ]
        for step in (reversed(steps) if undo else steps):
            step()

    def build(self) -> km.Circuit:
        for word, value in zip(self.h, IV):  # digest starts at zero: write the IV with X gates.
            self.b.x([word[k] for k in range(WORD) if (value >> k) & 1])

        state = list(self.h)
        for t in range(64):
            if t >= 16:
                self.schedule(t)
            state = self.round(t, state)
        assert all(now is start for now, start in zip(state, self.h)), 'state registers did not line up'

        for word, value in zip(self.h, IV):  # Feed-forward: add the input chaining value.
            self.b.iadd(value, target=word)

        for t in reversed(range(16, 64)):  # Restore the block.
            self.schedule(t, undo=True)

        self.b.free(self.tmp)
        return self.b.finish_circuit()


def block_bits(blocks: list[bytes]) -> np.ndarray:
    """Blocks as register bits, shape (512, n): bit b of byte i is at 32 (i // 4) + 8 (3 - i % 4) + b."""
    bits = np.zeros((512, len(blocks)), dtype=bool)
    for shot, block in enumerate(blocks):
        for i, byte in enumerate(block):
            for b in range(8):
                bits[32 * (i // 4) + 8 * (3 - i % 4) + b, shot] = (byte >> b) & 1
    return bits


def digest_bytes(bits: np.ndarray) -> list[bytes]:
    """The inverse of `block_bits`, for the 256-qubit digest register."""
    out = []
    for shot in range(bits.shape[1]):
        digest = bytearray(32)
        for i in range(32):
            for b in range(8):
                digest[i] |= int(bits[32 * (i // 4) + 8 * (3 - i % 4) + b, shot]) << b
        out.append(bytes(digest))
    return out


def pad(message: bytes) -> bytes:
    assert len(message) <= 55, 'only messages that fit one block'
    return message + b'\x80' + bytes(55 - len(message)) + (8 * len(message)).to_bytes(8, 'big')


def check(circuit: km.Circuit, shots: int = 1024) -> None:
    """Checks the circuit against `hashlib.sha256` on random messages of every length 0..55."""
    registers = circuit.register_data
    block, digest = km.array(list(registers['block'])), km.array(list(registers['digest']))
    in_register = set(registers['block']) | set(registers['digest'])
    scratch = km.array([km.q(i) for i in range(circuit.num_qubits) if km.q(i) not in in_register])

    rng = np.random.default_rng(2026)
    batch = 256
    sim = km.Simulator(batch_size=batch, debug_print=False, seed=1)
    for start in range(0, shots, batch):
        messages = [rng.bytes((start + i) % 56) for i in range(batch)]
        inputs = block_bits([pad(m) for m in messages])
        sim.clear_for_shot()
        sim.write_across_shots(block, inputs)
        sim.do(circuit)
        assert digest_bytes(sim.read_across_shots(digest)) == [hashlib.sha256(m).digest() for m in messages], \
            'digest differs from hashlib'
        assert np.array_equal(sim.read_across_shots(block), inputs), 'block was not restored'
        assert not sim.read_across_shots(scratch).any(), 'scratch is not clean'
        assert not np.asarray(sim.read_phase_flipped_across_shots()).any(), 'phase flipped'


def main() -> None:
    circuit = Sha256Builder().build()
    check(circuit)
    path = pathlib.Path(__file__).with_name('circuit.kmb')
    circuit.to_file(path, format='kmb')
    stats = circuit.operation_statistics()
    print(f'Wrote {path.name}: {circuit.num_qubits} qubits, {stats.num_toffoli_like} Toffolis, '
          f'{len(circuit)} operations, {path.stat().st_size} bytes. Matches hashlib on 1024 messages.')


if __name__ == '__main__':
    main()
