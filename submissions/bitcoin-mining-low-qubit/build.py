"""Builds a low-qubit circuit for the problem `bitcoin-mining-v1`: 1,072 qubits.

    |extranonce, nonce>  ->  (-1)^f |extranonce, nonce>

with f = 1 when the masked block hash is below the target. The contract is
sha256_verifier/docs/bitcoin-mining-v1.md.

The oracle is a chain of five compressions:

    inner1 -> root -> mid -> inner2 -> hash

The baseline keeps all five results to the end. Here a value is measured away in the X
basis as soon as nothing ahead needs it. That frees its qubits at once and leaves a phase
(-1)^(m.v), with m the measured bits and v the value. The phase is removed later: the value
is computed again and a Z is applied to each of its bits whose measured bit was one.

What is left to hold at one time is a single compression and its inputs. The largest is
the header's second block, the only compression whose starting state is not classical:

      48  extranonce, idle
     256  mid, kept for the addition that ends the compression
     256  the state being worked on
     512  the message schedule, which includes the nonce and the root's last word
    ----
    1072

From round 30 on that compression has no qubit to spare, so its last 34 rounds are built
from the pieces of the 768-qubit compression in ../zero-scratch: additions that keep their
carries in the wires of the number being added, Sigma functions and Ch and Maj computed in
place, constants as signed digits. Its first 30 rounds have room, because the padding words
of the block are constants and get no qubits until the schedule overwrites them. Those
rounds and the other four compressions use the baseline's arithmetic.

A compression's expanded message schedule is measured away too instead of being rewound,
wherever the next step would measure the block's quantum words away anyway.

The order of work, where P is "compute", U is "uncompute by running backwards", G is
"measure away" and Z is "remove the phase of an earlier G":

    forward   P1 P2 G1 P3 G2 P4 G3 P5 [phase] U5 G4
    pass 1    P1 Z1 P2 Z2 G1 P3 Z3 G2 P4 Z4 U4 G3
    pass 2    P1 Z1 P2 Z2 G1 P3 Z3 U3 G2
    pass 3    P1 Z1 P2 Z2 U2 U1

Usage, from this directory:

    uv run --project ../../sha256_verifier python build.py
"""

from __future__ import annotations

import dataclasses
import importlib.util
import pathlib
from typing import Callable

import kickmix as km

_HERE = pathlib.Path(__file__).parent


def _load(name: str, directory: str):
    spec = importlib.util.spec_from_file_location(name, _HERE.parent / directory / 'build.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


baseline = _load('bitcoin_baseline_build', 'bitcoin-mining-baseline')
zero_scratch = _load('zero_scratch_build', 'zero-scratch')

WORD, K, IV = baseline.WORD, baseline.K, baseline.IV
MASK = (1 << WORD) - 1
PAD256, PAD640 = baseline.PAD256, baseline.PAD640
BIG_SIGMA0, BIG_SIGMA1 = baseline.BIG_SIGMA0, baseline.BIG_SIGMA1
SMALL_SIGMA0, SMALL_SIGMA1 = baseline.SMALL_SIGMA0, baseline.SMALL_SIGMA1

QUBITS = 1072

# In the header's second block, the first round built without scratch. Before round t the
# schedule holds 4 + max(0, t - 19) words in qubits, so through round 29 at least two words
# are unallocated: 32 qubits for a Sigma, Ch or Maj value and 31 for an adder's carries.
TIGHT_FROM = 30

# A word of a message block: 32 qubits, or a constant that has no qubits yet.
Word = km.array | int


def sigma_of(value: int, sigma: tuple[tuple[int, ...], int | None]) -> int:
    rotations, shift = sigma
    out = 0
    for r in rotations:
        out ^= (value >> r | value << (WORD - r)) & MASK
    return out ^ (value >> shift if shift is not None else 0)


@dataclasses.dataclass
class Window:
    """A message block, laid out for a schedule that runs in place.

    Attributes:
        words: W_0..W_15. A quantum word is the caller's own register, or a copy of it.
        load: XORs the classical words, and any copied quantum ones, into the fresh
            registers. Its own inverse.
        fresh: The registers this window allocated.
    """
    words: list[Word]
    load: Callable[[], None]
    fresh: list[km.array]


class LowQubitBuilder(baseline.BitcoinOracleBuilder):
    """Emits the oracle. Reuses the baseline's addition steps, mask, target and comparison."""

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
        b.set_max_qubits(QUBITS)  # Allocating one qubit more raises.
        self.w: list[Word] = []  # The schedule: W_s is `w[s % 16]`.
        self.constants: dict[int, int] = {}  # Schedule positions given qubits, and the constant they started as.
        self.tmp: km.array | None = None
        self.undo: list = []  # Unused; the baseline's helpers expect it.
        self.owed: dict[str, km.array] = {}  # Measured bits of each value whose phase is not yet removed.

    # ---- registers ---------------------------------------------------------------------

    def fresh_words(self, count: int) -> list[km.array]:
        return self.words(self.b.alloc_qubits(count * WORD))

    @staticmethod
    def flat(words: list[km.array]) -> km.array:
        return km.array([word[k] for word in words for k in range(len(word))])

    def set_words(self, words: list[km.array], values: list) -> None:
        """`words ^= values`, each value a constant or 32 bits or qubits. Its own inverse."""
        for word, value in zip(words, values):
            if isinstance(value, int):
                ones = [word[k] for k in range(WORD) if value >> k & 1]
                if ones:
                    self.b.x(ones)
            else:
                self.b.cx(value, word)

    # ---- measuring a value away, and paying for it later ---------------------------------

    def measure_away(self, name: str, words: list[km.array]) -> None:
        """Frees `words` by X-basis measurement. Leaves the phase (-1)^(bits . value)."""
        assert name not in self.owed
        qubits = self.flat(words)
        bits = self.b.alloc_bits(len(qubits))
        self.b.hmr(qubits, bits)
        self.b.free(qubits)
        self.owed[name] = bits

    def settle(self, name: str, words: list[km.array]) -> None:
        """Removes the phase left by `measure_away(name, ...)`; `words` hold the same value again."""
        bits = self.owed.pop(name)
        self.b.cz(bits, self.flat(words))  # A Z on each qubit whose measured bit is one.
        self.b.free(bits)

    # ---- rounds and schedule with the baseline's arithmetic ---------------------------------

    def add_value(self, offset: Word, target: km.array, subtract: bool) -> None:
        """`target += offset`, or `-=`. Adding the constant zero emits nothing."""
        if isinstance(offset, int):
            offset &= MASK
            if not offset:
                return
        self.add(offset, target, subtract)

    def add_sigma(self, source: Word, sigma, target: km.array, subtract: bool) -> None:
        if isinstance(source, int):
            self.add_value(sigma_of(source, sigma), target, subtract)
        else:
            self.add_linear(source, sigma, target, subtract)

    def add_round_constant_and_message(self, t: int, target: km.array, subtract: bool) -> None:
        """`target += K_t + W_t`, as one addition when W_t is a constant."""
        message = self.w[t % 16]
        if isinstance(message, int):
            self.add_value(K[t] + message, target, subtract)
        else:
            self.add_value(K[t], target, subtract)
            self.add_value(message, target, subtract)

    def round_forward(self, t: int, state: list[km.array]) -> list[km.array]:
        a, b, c, d, e, f, g, h = state
        self.add_linear(e, BIG_SIGMA1, h, False)
        self.add_ch(e, f, g, h, False)
        self.add_round_constant_and_message(t, h, False)  # h now holds T1.
        self.add(h, d, False)  # d now holds the new e.
        self.add_linear(a, BIG_SIGMA0, h, False)
        self.add_maj(a, b, c, h, False)  # h now holds the new a.
        return [h, a, b, c, d, e, f, g]

    def round_backward(self, t: int, state: list[km.array]) -> list[km.array]:
        h, a, b, c, d, e, f, g = state  # The registers as `round_forward` returned them.
        self.add_maj(a, b, c, h, True)
        self.add_linear(a, BIG_SIGMA0, h, True)
        self.add(h, d, True)
        self.add_round_constant_and_message(t, h, True)
        self.add_ch(e, f, g, h, True)
        self.add_linear(e, BIG_SIGMA1, h, True)
        return [a, b, c, d, e, f, g, h]

    def give_qubits(self, position: int) -> None:
        """Writes the constant at a schedule position into fresh qubits."""
        value = self.w[position]
        self.constants[position] = value
        self.w[position] = self.b.alloc_qubits(WORD)
        self.set_words([self.w[position]], [value])

    def take_qubits(self, position: int) -> None:
        """The reverse: the position holds its constant again."""
        value = self.constants.pop(position)
        self.set_words([self.w[position]], [value])
        self.b.free(self.w[position])
        self.w[position] = value

    def expand(self, t: int) -> None:
        """Turns W_(t-16) into W_t in place: W_t = W_(t-16) + sigma0(W_(t-15)) + W_(t-7) + sigma1(W_(t-2))."""
        if isinstance(self.w[t % 16], int):
            self.give_qubits(t % 16)
        target = self.w[t % 16]
        self.add_sigma(self.w[(t - 15) % 16], SMALL_SIGMA0, target, False)
        self.add_value(self.w[(t - 7) % 16], target, False)
        self.add_sigma(self.w[(t - 2) % 16], SMALL_SIGMA1, target, False)

    def contract(self, t: int) -> None:
        """Turns W_t back into W_(t-16)."""
        target = self.w[t % 16]
        self.add_sigma(self.w[(t - 2) % 16], SMALL_SIGMA1, target, True)
        self.add_value(self.w[(t - 7) % 16], target, True)
        self.add_sigma(self.w[(t - 15) % 16], SMALL_SIGMA0, target, True)
        if t < 32 and t % 16 in self.constants:
            self.take_qubits(t % 16)

    # ---- one compression with the baseline's arithmetic -----------------------------------

    def open_window(self, window: Window) -> None:
        assert not self.constants
        self.w = list(window.words)
        window.load()
        self.tmp = self.b.alloc_qubits(WORD)

    def close_window(self, window: Window) -> None:
        """The schedule holds W_0..W_15 again: takes the loaded part out and frees it."""
        assert not self.constants
        window.load()
        for register in window.fresh:
            self.b.free(register)
        self.b.free(self.tmp)
        self.w, self.tmp = [], None

    def measure_window_away(self, name: str) -> None:
        """Frees the expanded schedule, W_48..W_63, by measurement.

        The quantum words of the block were among its registers and are gone with it.
        """
        self.measure_away(name, self.w)
        self.b.free(self.tmp)
        self.w, self.tmp, self.constants = [], None, {}

    def compute(self, start: list, window: Window, *, settle: str | None = None,
                then: str = 'rewind') -> list[km.array]:
        """Returns eight fresh words holding `compress(start, block)`.

        Args:
            start: The starting state, eight constants or classical words.
            window: The block.
            settle: A name under which the expanded schedule was measured away earlier; the
                phase that left is removed.
            then: What becomes of the expanded schedule. `'rewind'` restores the block and
                frees what the window allocated. `'keep'` leaves it for
                `uncompute(..., expanded=True)`. Any other string measures it away under
                that name.
        """
        state = self.fresh_words(8)
        self.set_words(state, start)
        self.open_window(window)
        registers = list(state)
        for t in range(64):
            if t >= 16:
                self.expand(t)
            registers = self.round_forward(t, registers)
        assert all(now is then_ for now, then_ in zip(registers, state)), 'state registers did not line up'
        for word, offset in zip(state, start):
            self.add(offset, word, False)
        if settle is not None:
            self.settle(settle, self.w)
        if then == 'rewind':
            for t in reversed(range(16, 64)):
                self.contract(t)
            self.close_window(window)
        elif then != 'keep':
            self.measure_window_away(then)
        return state

    def uncompute(self, state: list[km.array], start: list, window: Window, *, expanded: bool = False,
                  settle: str | None = None) -> None:
        """Runs `compute` backwards and frees `state`."""
        if not expanded:
            self.open_window(window)
            for t in range(16, 64):
                self.expand(t)
        if settle is not None:
            self.settle(settle, self.w)
        for word, offset in zip(state, start):
            self.add(offset, word, True)
        registers = list(state)
        for t in reversed(range(64)):
            registers = self.round_backward(t, registers)
            if t >= 16:
                self.contract(t)
        self.close_window(window)
        self.set_words(state, start)
        for word in state:
            self.b.free(word)

    # ---- the blocks of the four compressions that have room --------------------------------

    def coinbase_window(self) -> Window:
        """extranonce ‖ tail, on a copy of the extranonce.

        The copy costs 48 qubits where there is room for them. It lets the expanded schedule
        be measured away whole: the schedule never runs over the search register itself.
        """
        fresh = self.fresh_words(16)
        values = ([self.extranonce[0:32], km.array(list(self.tail[0:16]) + list(self.extranonce[32:48]))]
                  + self.words(self.tail[16:]))
        return Window(list(fresh), lambda: self.set_words(fresh, values), fresh)

    def digest_window(self, digest: list[km.array]) -> Window:
        """A 32-byte digest, in place, and its padding as constants."""
        return Window(list(digest) + list(PAD256), lambda: None, [])

    def header_window_1(self, root: list[km.array]) -> Window:
        """version ‖ prev_hash ‖ root[0:28], the root's first seven words in place."""
        head = self.fresh_words(9)
        values = [self.version] + self.words(self.prev_hash)
        return Window(head + root[0:7], lambda: self.set_words(head, values), head)

    # ---- the header's second block ----------------------------------------------------------

    def header_block_2(self, mid: list[km.array], root7: km.array):
        """Runs `inner2 = compress(mid, root[28:32] ‖ time ‖ bits ‖ nonce ‖ pad640)` to its end.

        `mid` stays as it is and a copy of it is worked on. The schedule runs in place over
        the root's last word and the nonce.

        Returns:
            `(work, registers, gates, rewind)`. `work` holds inner2 and the schedule is
            left expanded. `registers` are the state registers as they stood after round
            `TIGHT_FROM - 1`. `gates` are the scratch-free rounds that were emitted, as
            tuples of qubit numbers: one for X, two for CX, three for CCX, each its own
            inverse. `rewind`, not yet emitted, takes the schedule back to where the
            scratch-free rounds started.
        """
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
        assert b.num_allocated_qubits == QUBITS, 'the scratch-free rounds should start with every qubit in use'

        def numbers(words: list[km.array]) -> list[list[int]]:
            return [[word[k].id for k in range(WORD)] for word in words]

        z = zero_scratch.Builder()
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

    def leave_tight_rounds(self) -> None:
        """The schedule is back where round `TIGHT_FROM` found it: frees the scratch again."""
        for position in sorted(self.constants):
            if position + 16 >= TIGHT_FROM:
                self.take_qubits(position)
        self.tmp = self.b.alloc_qubits(WORD)

    def close_header_block_2(self) -> None:
        assert not self.constants
        self.set_words(self.loaded, [self.time, self.bits])
        for register in self.loaded:
            self.b.free(register)
        self.b.free(self.tmp)
        self.w, self.tmp = [], None

    def emit(self, gates) -> None:
        """Appends X, CX and CCX gates given as tuples of qubit numbers, in order."""
        emitters = {1: self.b.x, 2: self.b.cx, 3: self.b.ccx}
        run: list[tuple] = []

        def flush() -> None:
            if run:
                columns = [km.array([km.q(gate[i]) for gate in run]) for i in range(len(run[0]))]
                emitters[len(run[0])](*columns)
                run.clear()

        for gate in gates:
            if run and len(gate) != len(run[0]):
                flush()
            run.append(gate)
        flush()

    def inner2(self, mid: list[km.array], root7: km.array) -> list[km.array]:
        work, _, _, rewind = self.header_block_2(mid, root7)
        self.emit(rewind)
        self.leave_tight_rounds()
        for t in reversed(range(16, TIGHT_FROM)):
            self.contract(t)
        self.close_header_block_2()
        return work

    def settle_inner2(self, mid: list[km.array], root7: km.array) -> None:
        """Computes inner2, removes the phase owed on it, and uncomputes it."""
        work, registers, gates, _ = self.header_block_2(mid, root7)
        self.settle('inner2', work)
        self.emit(reversed(gates))
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

    # ---- the oracle ----------------------------------------------------------------------------

    def inner1(self, *, settle: bool = True) -> list[km.array]:
        """Computes inner1. Its schedule is measured away: only the extranonce's copy was in it."""
        return self.compute(self.words(self.midstate), self.coinbase_window(),
                            settle='schedule of inner1' if settle else None, then='schedule of inner1')

    def root(self, inner1: list[km.array], *, settle: bool = True) -> list[km.array]:
        """Computes the root. inner1 is measured away with the schedule it was expanded into."""
        return self.compute(list(IV), self.digest_window(inner1),
                            settle='schedule of root' if settle else None, then='schedule of root')

    def mid(self, root: list[km.array], *, settle: bool = True) -> list[km.array]:
        """Computes mid. The root's first seven words are measured away with the schedule."""
        return self.compute(list(IV), self.header_window_1(root),
                            settle='schedule of mid' if settle else None, then='schedule of mid')

    def build(self) -> km.Circuit:
        b = self.b
        iv = list(IV)

        # Forward: reach the block hash holding one earlier result at a time.
        inner1 = self.inner1(settle=False)
        root = self.root(inner1, settle=False)
        mid = self.mid(root, settle=False)
        inner2 = self.inner2(mid, root[7])
        self.measure_away('mid', mid)
        self.measure_away('root[28:32]', root[7:8])

        window = self.digest_window(inner2)
        digest = self.compute(iv, window, then='keep')
        masked = self.flat(digest[5:8])
        b.cx(self.mask, masked)
        self.phase(digest)
        b.cx(self.mask, masked)
        self.uncompute(digest, iv, window, expanded=True)
        self.measure_away('inner2', inner2)

        # Pass 1: back to mid, to remove the phase owed on inner2.
        root = self.root(self.inner1())
        self.settle('root[28:32]', root[7:8])
        mid = self.mid(root)
        self.settle('mid', mid)
        self.settle_inner2(mid, root[7])
        self.measure_away('mid', mid)
        self.measure_away('root[28:32]', root[7:8])

        # Pass 2: back to root, to remove the phase owed on mid.
        root = self.root(self.inner1())
        self.settle('root[28:32]', root[7:8])
        window = self.header_window_1(root)
        mid = self.compute(iv, window, settle='schedule of mid', then='keep')
        self.settle('mid', mid)
        self.uncompute(mid, iv, window, expanded=True)
        self.measure_away('root', root)

        # Pass 3: back to inner1, to remove the phase owed on root; then nothing is left.
        inner1 = self.inner1()
        window = self.digest_window(inner1)
        root = self.compute(iv, window, settle='schedule of root', then='keep')
        self.settle('root', root)
        self.uncompute(root, iv, window, expanded=True)
        self.uncompute(inner1, self.words(self.midstate), self.coinbase_window(), settle='schedule of inner1')

        assert not self.owed, f'phases never removed: {sorted(self.owed)}'
        assert b.num_allocated_qubits == 80, 'something was not freed'
        return b.finish_circuit()


if __name__ == '__main__':
    baseline.main(LowQubitBuilder, __file__)
