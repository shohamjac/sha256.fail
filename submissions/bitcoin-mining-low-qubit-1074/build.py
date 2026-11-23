"""Builds a circuit for the problem `bitcoin-mining-v1` on 1,074 qubits.

    |extranonce, nonce>  ->  (-1)^f |extranonce, nonce>

This is ../bitcoin-mining-low-qubit with two more qubits. That circuit's largest step, the
header's second block, has no free qubit in rounds 30 to 63, and there a round constant
is added as signed binary digits at 558 Toffolis on average. Two clean qubits are enough
for the constant adder of Gidney, "A classical-quantum adder with constant workspace and
linear gates" (arXiv:2507.23079), which takes 3n - 7 Toffolis: 89 for a 32-bit constant.

The adder, for a constant d with lowest bit one (lower zero bits are skipped):

1. Ripple through the addition with two carry qubits. Once the carry into bit k has been
   used it is XORed into a borrowed busy qubit g_k and measured in the X basis. That leaves
   the phase (-1)^(m_k c_k), with m_k the measured bit and c_k the carry.
2. Apply Z to g_k when m_k is one.
3. XOR every carry into the borrowed qubits a second time, which restores them. The carries
   of x + d are the borrows of (x + d) - d, so they are computed from the sum, with the
   borrowed qubits themselves as the workspace (Häner, Roetteler and Svore,
   arXiv:1611.07995): each Toffoli is applied twice, once before its control is toggled
   and once after, so that the control's own unknown value cancels.
4. Apply Z to g_k when m_k is one, again. The two Z's see g_k with and without the carry,
   so together they are (-1)^(m_k c_k), which removes the phase of step 1.

Everything else is as in ../bitcoin-mining-low-qubit, whose generator this file imports.

Usage, from this directory:

    uv run --project ../../sha256_verifier python build.py
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import kickmix as km
import numpy as np

_spec = importlib.util.spec_from_file_location(
    'low_qubit_build', pathlib.Path(__file__).parent.parent / 'bitcoin-mining-low-qubit' / 'build.py')
low_qubit = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = low_qubit  # Its dataclass looks its own module up by name.
_spec.loader.exec_module(low_qubit)

baseline, zero_scratch = low_qubit.baseline, low_qubit.zero_scratch
WORD, MASK, PAD640, TIGHT_FROM = low_qubit.WORD, low_qubit.MASK, low_qubit.PAD640, low_qubit.TIGHT_FROM

QUBITS = 1074
CARRY_QUBITS = 2


def add_constant(b: km.CircuitBuilder, value: int, target: list, borrowed: list) -> None:
    """`target += value` mod 2^len(target), with two clean qubits and measured carries.

    Args:
        b: Where the instructions go. Two qubits and some bits are allocated and freed.
        value: The constant.
        target: Qubits of the number, least significant first.
        borrowed: Busy qubits in any state, none of them in `target`. They are restored.
            At least `len(target) - 2` of them.
    """
    value %= 1 << len(target)
    if not value:
        return
    low = (value & -value).bit_length() - 1  # Zero low bits of the constant change nothing below them.
    x = list(target[low:])
    n = len(x)
    d = [value >> (low + k) & 1 for k in range(n)]  # d[0] is one.
    if n == 1:
        b.x(x[0])
        return

    def carry_out(k: int, carry, into) -> None:
        """`into ^= maj(x_k, d_k, carry)`: the AND of the two qubits, or their OR when d_k is one."""
        if d[k]:
            b.x(carry), b.x(x[k])
        b.ccx(carry, x[k], into)
        if d[k]:
            b.x(carry), b.x(x[k]), b.x(into)

    def finish_bit(k: int, carry) -> None:
        b.cx(carry, x[k])
        if d[k]:
            b.x(x[k])

    # Step 1. The carry into bit 1 is x_0 itself, since d_0 is one.
    if n == 2:
        finish_bit(1, x[0])
        b.x(x[0])
        return
    g = {k: borrowed[k - 2] for k in range(2, n)}  # g[k] is toggled by the carry into bit k.
    current, following = b.alloc_qubits(CARRY_QUBITS)
    measured = b.alloc_bits(n - 2)
    carry_out(1, x[0], current)
    finish_bit(1, x[0])
    b.x(x[0])
    for k in range(2, n):
        if k < n - 1:
            carry_out(k, current, following)
        finish_bit(k, current)
        b.cx(current, g[k])
        b.hmr(current, measured[k - 2])
        current, following = following, current
    b.free(current), b.free(following)

    # Steps 2 to 4. With s the sum now in x, the carry into bit k + 1 is
    # maj(not s_k, d_k, c_k) = c_k p_k xor q_k, where p_k = not s_k xor d_k and q_k = d_k and not s_k.
    def toggle(k: int, control) -> None:
        """`g[k + 1] ^= control and p_k`."""
        if not d[k]:
            b.x(x[k])
        b.ccx(control, x[k], g[k + 1])
        if not d[k]:
            b.x(x[k])

    marked = km.array([g[k] for k in range(2, n)])
    b.cz(measured, marked)
    for k in range(n - 2, 1, -1):
        toggle(k, g[k])  # While g[k] is as it was found.
    for k in range(1, n - 1):
        if k == 1:
            b.x(x[0])  # The carry into bit 1 is not s_0.
            toggle(1, x[0])
            b.x(x[0])
        else:
            toggle(k, g[k])  # Now g[k] has been toggled by the carry into bit k.
        if d[k]:
            b.cx(x[k], g[k + 1])
            b.x(g[k + 1])
    b.cz(measured, marked)
    b.free(measured)


def check_add_constant(shots: int = 256) -> None:
    """Runs the adder on random numbers, constants and borrowed qubits, at several widths."""
    rng = np.random.default_rng(7)
    for n in (1, 2, 3, 4, 5, 8, 32):
        for value in {0, 1, (1 << n) - 1, 1 << (n - 1), *(int(v) for v in rng.integers(0, 1 << n, size=12))}:
            b = km.CircuitBuilder()
            target = b.create_quantum_register(n, 'target')
            borrowed = b.create_quantum_register(max(1, n - 2), 'borrowed')
            add_constant(b, value, list(target), list(borrowed))
            circuit = b.finish_circuit()
            assert circuit.num_qubits <= n + max(1, n - 2) + CARRY_QUBITS
            sim = km.Simulator(batch_size=shots, debug_print=False, seed=3)
            sim.clear_for_shot()
            numbers = [int(v) for v in rng.integers(0, 1 << n, size=shots)]
            garbage = rng.integers(0, 2, size=(len(borrowed), shots)).astype(bool)
            sim.write_across_shots(target, np.array([[v >> k & 1 for v in numbers] for k in range(n)], dtype=bool))
            sim.write_across_shots(borrowed, garbage)
            sim.do(circuit)
            got = sim.read_across_shots(target)
            want = np.array([[(v + value) >> k & 1 for v in numbers] for k in range(n)], dtype=bool)
            assert np.array_equal(got, want), f'wrong sum, width {n}, constant {value}'
            assert np.array_equal(sim.read_across_shots(borrowed), garbage), 'borrowed qubits not restored'
            rest = km.array([km.q(i) for i in range(n + len(borrowed), circuit.num_qubits)])
            assert len(rest) == 0 or not sim.read_across_shots(rest).any(), 'carry qubits not clean'
            assert not np.asarray(sim.read_phase_flipped_across_shots(), dtype=bool).any(), 'a phase was left'


class TightRounds(zero_scratch.Builder):
    """The scratch-free rounds, with a constant addition recorded as one entry of the gate list.

    The entry is `('add', value, target, borrowed)`. Its inverse is the same with the value
    negated; every other gate is its own inverse.
    """

    def add_const(self, value: int, target: list[int], borrowed: list[int]) -> None:
        if value & MASK:
            self.gates.append(('add', value & MASK, tuple(target), tuple(borrowed)))


def backwards(gates):
    for gate in reversed(gates):
        yield ('add', -gate[1] & MASK, gate[2], gate[3]) if gate[0] == 'add' else gate


class Builder1074(low_qubit.LowQubitBuilder):
    """`LowQubitBuilder` with the constant adder above in the rounds that have no scratch."""

    def __init__(self) -> None:
        super().__init__()
        self.b.set_max_qubits(QUBITS)

    def header_block_2(self, mid: list[km.array], root7: km.array):
        """As in `LowQubitBuilder`, but the scratch-free rounds leave two qubits for carries."""
        b = self.b
        work = self.fresh_words(8)
        for source, target in zip(mid, work):
            b.cx(source, target)
        self.loaded = self.fresh_words(2)
        self.set_words(self.loaded, [self.time, self.bits])
        assert not self.constants
        self.w = [root7, self.loaded[0], self.loaded[1], self.nonce] + list(PAD640)
        self.tmp = b.alloc_qubits(WORD)

        registers = list(work)
        for t in range(TIGHT_FROM):
            if t >= 16:
                self.expand(t)
            registers = self.round_forward(t, registers)

        b.free(self.tmp)
        for position in range(16):
            if isinstance(self.w[position], int):
                self.give_qubits(position)
        assert b.num_allocated_qubits == QUBITS - CARRY_QUBITS, 'only the carry qubits should be free'

        def numbers(words: list[km.array]) -> list[list[int]]:
            return [[word[k].id for k in range(WORD)] for word in words]

        z = TightRounds()
        z.w, z.h = numbers(self.w), numbers(work)
        state = numbers(registers)
        for t in range(TIGHT_FROM, 64):
            if t < 62:  # W_62 and W_63 are added to the state term by term, never stored.
                z.schedule(t)
            state = z.round(t, state)
        assert state == z.h, 'state registers did not line up'
        for source, target in zip(numbers(mid), z.h):
            z.add(source, target)
        gates, z.gates = z.gates, []
        for t in reversed(range(TIGHT_FROM, 62)):
            z.schedule(t, undo=True)
        self.emit(gates)
        return work, registers, gates, z.gates

    def emit(self, gates) -> None:
        """Appends X, CX and CCX gates given as tuples of qubit numbers, and constant additions."""
        run: list[tuple] = []

        def flush() -> None:
            super(Builder1074, self).emit(run)
            run.clear()

        for gate in gates:
            if gate[0] == 'add':
                flush()
                _, value, target, borrowed = gate
                add_constant(self.b, value, [km.q(i) for i in target], [km.q(i) for i in borrowed])
            else:
                run.append(gate)
        flush()

    def settle_inner2(self, mid: list[km.array], root7: km.array) -> None:
        """Computes inner2, removes the phase owed on it, and uncomputes it."""
        work, registers, gates, _ = self.header_block_2(mid, root7)
        self.settle('inner2', work)
        self.emit(backwards(gates))
        self.leave_tight_rounds()
        for t in reversed(range(TIGHT_FROM)):
            registers = self.round_backward(t, registers)
            if t >= 16:
                self.contract(t)
        assert all(now is then for now, then in zip(registers, work)), 'state registers did not line up'
        for source, target in zip(mid, work):
            self.b.cx(source, target)
            self.b.free(target)
        self.close_header_block_2()


if __name__ == '__main__':
    check_add_constant()
    baseline.main(Builder1074, __file__)
