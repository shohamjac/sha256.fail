"""Builds a circuit for the problem `bitcoin-mining-v1` on 914 qubits.

    |extranonce, nonce>  ->  (-1)^f |extranonce, nonce>

This is ../bitcoin-mining-low-qubit (1,072 qubits) with a different header's second block.
There the block held 16 schedule words next to its two states. Here it holds 11 registers
of schedule, and computes the words it does not hold again each time they are needed.

Only two of the block's 16 message words depend on the search register: W_0, the root's
last word, and W_3, the nonce. Every schedule word is a function of those two, so a word
that is not held can be computed from them, at a cost that grows by about a quarter for
each step further into the schedule.

A schedule step is W_t = W_(t-16) + sigma0(W_(t-15)) + W_(t-7) + sigma1(W_(t-2)).

- Seven registers hold the words in progress. W_t is built in the register of W_(t-7).
  sigma1(W_t) is added to the register that will become W_(t+2) as soon as W_t exists, so
  after its own round W_t is only the start of W_(t+7).
- W_(t-16) and W_(t-15) are too old to be held. W_(t-15) is computed from the two base
  words in the two registers that are left, used, kept one step as the next W_(t-16), and
  measured away. A planner picks, for the registers free at that moment, the cheapest way:
  which input to build on, and whether an input that enters without a sigma is computed
  whole or added term by term, which needs no register for it.
- The two base words are kept as W_16 and W_18 rather than W_0 and W_3. W_19 to W_24 are
  then each an invertible function of W_18 (and W_16), made in place and undone, so the
  recursion reaches them without a register of their own.

A word measured away leaves a phase. All of them are removed when the block is uncomputed.
Uncomputing does not need the short schedule: mid is subtracted from the result and
measured away, which leaves room for the ordinary 16-word schedule in place, and the rounds
run backwards turn the working state into mid again.

Additions of classical values inside the recursion use the adder of Gidney, "A
classical-quantum adder with constant workspace and linear gates" (arXiv:2507.23079), with
two clean qubits and borrowed busy ones. Those two qubits are the 2 in 914.

No compression here uses the 32-qubit temporary of the baseline's arithmetic: Sigma, Ch and
Maj values are made in place. With it the header's first block would need 944 qubits.

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
WORD, MASK, PAD640, K = low_qubit.WORD, low_qubit.MASK, low_qubit.PAD640, low_qubit.K
SIGMA = {'s0': low_qubit.SMALL_SIGMA0, 's1': low_qubit.SMALL_SIGMA1}

QUBITS = 914
CARRY_QUBITS = 2  # What `add_classical` allocates.

# The words that are an invertible function of W_18: two chains, each step sigma1 of the one before.
EVEN_CHAIN = (20, 22, 24)
ODD_CHAIN = (19, 21, 23)
STREAM_FROM = 31  # The first step built in the register of W_(t-7).

BIG_SIGMA_NAME = {low_qubit.BIG_SIGMA0: 'S0', low_qubit.BIG_SIGMA1: 'S1',
                  low_qubit.SMALL_SIGMA0: 's0', low_qubit.SMALL_SIGMA1: 's1'}


def message_inputs(s: int) -> list[tuple[int, str | None]]:
    """The four words W_s is the sum of, each with the sigma applied to it."""
    return [(s - 2, 's1'), (s - 7, None), (s - 15, 's0'), (s - 16, None)]


def is_classical(s: int) -> bool:
    """W_0 and W_3 are quantum; the rest of the block is classical, and so is W_17."""
    return s == 17 or (s < 16 and s not in (0, 3))


def quantum_inputs(s: int) -> list[tuple[int, str | None]]:
    return [term for term in message_inputs(s) if not is_classical(term[0])]


# ---- planning: the cheapest way to compute a word in the registers that are free --------------
#
# A plan to put W_u in a new register:
#     ('copy', u)                      copy W_16 or W_18, and walk a chain from W_18 if u is on one
#     ('build', u, seed, plan, adds)   start from the register `plan` gives for the input `seed`
#                                      (or from the classical part of W_u when `seed` is None),
#                                      then add the other inputs
# A way to add sigma(W_p) to a register:
#     ('hand', p, sigma)               W_p is W_16, W_18 or on a chain: read it where it is
#     ('temp', p, sigma, plan)         compute W_p by `plan`, add it, measure it away
#     ('expand', p, adds)              no sigma: add the inputs of W_p one by one instead of W_p
#
# Costs are rough operation counts. They only rank the plans.

_ADD = 212  # One in-place addition.
_PROGRAM = {name: len(zero_scratch.LINEAR[name][0]) for name in ('s0', 's1')}
_CLASSICAL_ADD = 800
_MEASURE = 70
_COPY = 32
_CHAIN_COST = {16: 0, 18: 0}
for _chain in (EVEN_CHAIN, ODD_CHAIN):
    _cost = 0
    for _s in _chain:
        _cost += _PROGRAM['s1'] + _CLASSICAL_ADD + (2 * _CLASSICAL_ADD + _ADD + _PROGRAM['s0'] if _s == 19 else 0)
        _CHAIN_COST[_s] = _cost
_plans: dict = {}


def plan_word(u: int, registers: int) -> tuple[float, tuple | None]:
    """The cheapest plan for W_u in at most `registers` registers, its own included."""
    registers = min(registers, 8)
    if registers < 1:
        return float('inf'), None
    key = ('word', u, registers)
    if key not in _plans:
        if u in _CHAIN_COST:
            _plans[key] = (_COPY + _CHAIN_COST[u], ('copy', u))
        else:
            terms = quantum_inputs(u)
            best: tuple[float, tuple | None] = (float('inf'), None)
            for seed in [*terms, None]:
                cost, plan = 0.0, None
                if seed is not None:
                    cost, plan = plan_word(seed[0], registers)
                    cost += _PROGRAM.get(seed[1], 0) + _CLASSICAL_ADD
                adds = []
                for term in terms:
                    if term != seed:
                        term_cost, add = plan_add(term[0], term[1], registers - 1)
                        cost += term_cost
                        adds.append(add)
                if cost < best[0]:
                    best = (cost, ('build', u, seed, plan, tuple(adds)))
            _plans[key] = best
    return _plans[key]


def plan_add(p: int, sigma: str | None, registers: int) -> tuple[float, tuple | None]:
    """The cheapest way to add sigma(W_p) to a register, with `registers` registers to spare."""
    registers = max(0, min(registers, 8))
    key = ('add', p, sigma, registers)
    if key not in _plans:
        around = 2 * _PROGRAM.get(sigma, 0)
        if p in _CHAIN_COST:
            _plans[key] = (2 * _CHAIN_COST[p] + _ADD + around, ('hand', p, sigma))
        else:
            cost, plan = plan_word(p, registers)
            best = (cost + _ADD + around + _MEASURE, ('temp', p, sigma, plan))
            if sigma is None:
                cost, adds = float(_CLASSICAL_ADD), []
                for q, name in quantum_inputs(p):
                    term_cost, add = plan_add(q, name, registers)
                    cost += term_cost
                    adds.append(add)
                if cost < best[0]:
                    best = (cost, ('expand', p, tuple(adds)))
            _plans[key] = best
    return _plans[key]


def add_classical(b: km.CircuitBuilder, value: list, target: list, borrowed: list) -> None:
    """`target += value` mod 2^len(target), with two clean qubits and measured carries.

    Gidney's adder (arXiv:2507.23079). The carries ripple through two qubits; each is XORed
    into a borrowed qubit and measured away. The carries of x + d are then computed again
    from the sum, with the borrowed qubits themselves as the workspace (Häner, Roetteler and
    Svore, arXiv:1611.07995), which restores the borrowed qubits. A Z on each borrowed qubit
    before and after, where the measured bit is one, removes the phase of the measurement.

    Args:
        b: Where the instructions go. Two qubits and some bits are allocated and freed.
        value: One entry per bit, least significant first: 0, 1, or a classical bit.
        target: Qubits of the number, least significant first.
        borrowed: Busy qubits in any state, none of them in `target`. They are restored.
            At least `len(target) - 1` of them.
    """
    d, x = list(value), list(target)
    while d and isinstance(d[0], int) and not d[0]:  # Known zero low bits change nothing below them.
        d, x = d[1:], x[1:]
    n = len(x)
    if all(isinstance(bit, int) and not bit for bit in d):
        return

    def x_if(k: int, qubit) -> None:
        if isinstance(d[k], int):
            if d[k]:
                b.x(qubit)
        else:
            b.cx(d[k], qubit)

    def x_if_not(k: int, qubit) -> None:
        if isinstance(d[k], int):
            if not d[k]:
                b.x(qubit)
        else:
            b.x(qubit), b.cx(d[k], qubit)

    if n == 1:
        x_if(0, x[0])
        return

    g = {k: borrowed[k - 1] for k in range(1, n)}  # g[k] is toggled by the carry into bit k.
    current, following = b.alloc_qubits(2)
    measured = b.alloc_bits(n - 1)
    for k in range(n):  # `current` holds the carry into bit k; the carry into bit 0 is zero.
        if k < n - 1:  # following ^= maj(x_k, d_k, carry): their AND, or their OR when d_k is one.
            x_if(k, current), x_if(k, x[k])
            b.ccx(current, x[k], following)
            x_if(k, current), x_if(k, x[k]), x_if(k, following)
        b.cx(current, x[k])
        x_if(k, x[k])
        if k:
            b.cx(current, g[k])
            b.hmr(current, measured[k - 1])
        current, following = following, current
    b.free(current), b.free(following)

    # With s the sum now in x, the carry into bit k + 1 is c_k p_k xor q_k, where
    # p_k = not s_k xor d_k and q_k = d_k and not s_k.
    def toggle(k: int) -> None:
        """`g[k + 1] ^= g[k] and p_k`."""
        x_if_not(k, x[k])
        b.ccx(g[k], x[k], g[k + 1])
        x_if_not(k, x[k])

    marked = km.array([g[k] for k in range(1, n)])
    b.cz(measured, marked)
    for k in range(n - 2, 0, -1):
        toggle(k)  # While g[k] still carries the carry into bit k.
    for k in range(n - 1):
        if k:
            toggle(k)  # Now g[k] is as it was found.
        if isinstance(d[k], int):
            if d[k]:
                b.cx(x[k], g[k + 1]), b.x(g[k + 1])
        else:
            b.push_condition(d[k])
            b.cx(x[k], g[k + 1]), b.x(g[k + 1])
            b.pop_condition()
    b.cz(measured, marked)
    b.free(measured)


def check_add_classical(shots: int = 256) -> None:
    """Runs the adder on random numbers and borrowed qubits, with constant and classical offsets."""
    rng = np.random.default_rng(7)
    for n in (1, 2, 3, 4, 5, 8, 32):
        for fixed in (None, 0, 1, (1 << n) - 1, 1 << (n - 1), int(rng.integers(0, 1 << n)), 2 * int(rng.integers(0, 1 << n - 1))):
            b = km.CircuitBuilder()
            target = b.create_quantum_register(n, 'target')
            borrowed = b.create_quantum_register(max(1, n - 1), 'borrowed')
            offset = b.create_classical_register(n, 'offset')
            value = [offset[k] for k in range(n)] if fixed is None else [fixed >> k & 1 for k in range(n)]
            add_classical(b, value, list(target), list(borrowed))
            circuit = b.finish_circuit()
            assert circuit.num_qubits <= n + len(borrowed) + 2
            sim = km.Simulator(batch_size=shots, debug_print=False, seed=3)
            sim.clear_for_shot()
            numbers = [int(v) for v in rng.integers(0, 1 << n, size=shots)]
            offsets = [int(v) for v in rng.integers(0, 1 << n, size=shots)] if fixed is None else [fixed] * shots
            garbage = rng.integers(0, 2, size=(len(borrowed), shots)).astype(bool)
            sim.write_across_shots(target, np.array([[v >> k & 1 for v in numbers] for k in range(n)], dtype=bool))
            sim.write_across_shots(borrowed, garbage)
            sim.write_across_shots(offset, np.array([[v >> k & 1 for v in offsets] for k in range(n)], dtype=bool))
            sim.do(circuit)
            want = np.array([[(v + o) >> k & 1 for v, o in zip(numbers, offsets)] for k in range(n)], dtype=bool)
            assert np.array_equal(sim.read_across_shots(target), want), f'wrong sum, width {n}, offset {fixed}'
            assert np.array_equal(sim.read_across_shots(borrowed), garbage), 'borrowed qubits not restored'
            rest = km.array([km.q(i) for i in range(n + len(borrowed), circuit.num_qubits)])
            assert len(rest) == 0 or not sim.read_across_shots(rest).any(), 'carry qubits not clean'
            assert not np.asarray(sim.read_phase_flipped_across_shots(), dtype=bool).any(), 'a phase was left'


def ids(register) -> list[int]:
    return [register[k].id for k in range(len(register))]


class Builder914(low_qubit.LowQubitBuilder):
    """`LowQubitBuilder` with a header's second block that holds 11 schedule words, and no temporary."""

    def __init__(self) -> None:
        super().__init__()
        b = self.b
        b.set_max_qubits(QUBITS)
        self.z = zero_scratch.Builder()  # Used only to write out additions and sigma programs.
        self.one = b.alloc_bits(1)[0]
        b.bit_store(self.one, True)
        self.sums: dict[tuple, km.array | int] = {}
        self.owed_words: dict[int, km.array] = {}  # XOR of the measured bits of every W_s measured away.
        self.w17 = self.classical_sum([(1, None), (2, 's0'), (10, None), (15, 's1')])

    # ---- every compression: Sigma, Ch and Maj without the 32-qubit temporary ---------------
    #
    # The base class writes a Sigma, Ch or Maj value into a temporary and adds that. Here the
    # value is made in place, as ../zero-scratch does, and Kickmix's adder adds it. That
    # leaves an adder's carries as the only scratch of a round.

    def add_linear(self, source: km.array, sigma, target: km.array, subtract: bool) -> None:
        """`target += sigma(source)`, with `source` turned into sigma(source) by CNOTs and back."""
        name = BIG_SIGMA_NAME[sigma]
        turned = self.sigma_in_place(name, [source[k] for k in range(WORD)])
        self.add(km.array(turned), target, subtract)
        self.sigma_in_place_inverse(name, turned)

    def add_ch(self, e: km.array, f: km.array, g: km.array, target: km.array, subtract: bool) -> None:
        """`target += Ch(e, f, g)`, with Ch = g ^ (e & (f ^ g)) computed onto g."""
        b = self.b
        b.cx(g, f), b.ccx(e, f, g)
        self.add(g, target, subtract)
        b.ccx(e, f, g), b.cx(g, f)

    def add_maj(self, a: km.array, b_: km.array, c: km.array, target: km.array, subtract: bool) -> None:
        """`target += Maj(a, b, c)`, with Maj = c ^ ((a ^ c) & (b ^ c)) computed onto c."""
        b = self.b
        b.cx(c, a), b.cx(c, b_), b.ccx(a, b_, c)
        self.add(c, target, subtract)
        b.ccx(a, b_, c), b.cx(c, b_), b.cx(c, a)

    def open_window(self, window) -> None:
        assert not self.constants
        self.w = list(window.words)
        window.load()

    def close_window(self, window) -> None:
        assert not self.constants
        window.load()
        for register in window.fresh:
            self.b.free(register)
        self.w = []

    def measure_window_away(self, name: str) -> None:
        self.measure_away(name, self.w)
        self.w, self.constants = [], {}

    # ---- classical arithmetic on the block's classical words, which costs nothing ---------

    def zero_bits(self, count: int) -> km.array:
        bits = self.b.alloc_bits(count)
        self.b.bit_store(bits, False)
        return bits

    def classical_word(self, s: int) -> km.array | int:
        """W_s of the header's second block, for a classical s."""
        if s == 1:
            return self.time
        if s == 2:
            return self.bits
        if s == 17:
            return self.w17
        assert 4 <= s <= 15, s
        return PAD640[s - 4]

    def classical_sum(self, terms: list[tuple[int, str | None]]) -> km.array | int:
        """The sum of classical words, each with a sigma applied or not: a constant, or 32 new bits."""
        key = tuple(sorted(terms, key=str))
        if key not in self.sums:
            constant, variable = 0, []
            for s, name in terms:
                word = self.classical_word(s)
                if isinstance(word, int):
                    constant += low_qubit.sigma_of(word, SIGMA[name]) if name else word
                else:
                    variable.append(self.classical_sigma(word, SIGMA[name]) if name else word)
            constant &= MASK
            if not variable:
                total = constant
            else:
                total = variable[0]
                for word in variable[1:]:
                    total = self.classical_add(total, word)
                if constant:
                    total = self.classical_add(total, constant)
            self.sums[key] = total
        return self.sums[key]

    def classical_sigma(self, word: km.array, sigma) -> km.array:
        rotations, shift = sigma
        out = self.zero_bits(WORD)
        for r in rotations:
            self.b.cx(km.array([word[(i + r) % WORD] for i in range(WORD)]), out)
        if shift is not None:
            self.b.cx(word[shift:], out[:WORD - shift])
        return out

    def classical_add(self, x: km.array, y: km.array | int) -> km.array:
        """`x + y` mod 2^32 in new classical bits, by a ripple of carries."""
        b = self.b
        out, carry = self.zero_bits(WORD), self.zero_bits(1)[0]

        def xor(target, source) -> None:
            if isinstance(source, int):
                if source:
                    b.cx(self.one, target)
            else:
                b.cx(source, target)

        def xor_and(target, u, v) -> None:  # target ^= u & v
            if isinstance(v, int):
                if v:
                    b.cx(u, target)
            else:
                b.push_condition(u)
                b.cx(v, target)
                b.pop_condition()

        for i in range(WORD):
            yi = y >> i & 1 if isinstance(y, int) else y[i]
            both = self.zero_bits(1)[0]
            xor(both, x[i]), xor(both, yi)
            xor(out[i], both), xor(out[i], carry)
            following = self.zero_bits(1)[0]  # maj(x, y, carry) = x y xor carry (x xor y)
            xor_and(following, x[i], yi), xor_and(following, carry, both)
            carry = following
        return out

    # ---- arithmetic that needs no scratch, on registers given as lists of qubits ---------

    def gates(self) -> None:
        """Emits what `self.z` has collected."""
        self.emit(self.z.gates)
        self.z.gates = []

    def complemented(self, register: list, subtract: bool) -> None:
        if subtract:  # b - a = not(not b + a)
            self.b.x(km.array(register))

    def tight_add(self, source: list, target: list, sigma: str | None = None, subtract: bool = False) -> None:
        """`target += sigma(source)`, or `-=`, with carries kept in the wires of `source`."""
        self.complemented(target, subtract)
        if sigma:
            self.z.add_linear(sigma, ids(source), ids(target))
        else:
            self.z.add(ids(source), ids(target))
        self.gates()
        self.complemented(target, subtract)

    def add_classical(self, value: km.array | int, target: list, subtract: bool = False) -> None:
        """`target += value` for a constant or 32 classical bits."""
        bits = [value >> k & 1 for k in range(WORD)] if isinstance(value, int) else [value[k] for k in range(WORD)]
        self.complemented(target, subtract)
        add_classical(self.b, bits, target, self.borrowed)
        self.complemented(target, subtract)

    def sigma_in_place(self, name: str, register: list) -> list:
        """Turns x into sigma(x) by CNOTs. Returns the register with its wires in the new order."""
        program, place = zero_scratch.LINEAR[name]
        self.emit([(register[c].id, register[t].id) for c, t in program])
        return [register[p] for p in place]

    def sigma_in_place_inverse(self, name: str, register: list) -> list:
        program, place = zero_scratch.LINEAR[name]
        wires = [None] * WORD
        for k in range(WORD):
            wires[place[k]] = register[k]
        self.emit([(wires[c].id, wires[t].id) for c, t in reversed(program)])
        return wires

    def measure_word_away(self, s: int, register: list) -> None:
        """Frees a register holding W_s. The phase is removed when the block is uncomputed."""
        b = self.b
        bits = b.alloc_bits(WORD)
        b.hmr(km.array(register), bits)
        b.free(km.array(register))
        if s not in self.owed_words:
            self.owed_words[s] = self.zero_bits(WORD)
        b.cx(bits, self.owed_words[s])
        b.free(bits)

    # ---- the schedule words that are functions of W_18 in place ----------------------------

    def chain_step(self, s: int, register: list, *, back: bool = False) -> list:
        """Turns W_(s-2) into W_s, or W_18 into W_19; or back.

        W_s = sigma1(W_(s-2)) + classical words, plus W_16 for s = 23.
        W_19 = W_3 + classical words, and W_18 = sigma0(W_3) + sigma1(W_16) + W_2.
        """
        classical = self.classical_sum([term for term in message_inputs(s) if is_classical(term[0])])
        if s == 19:
            from_w2 = self.classical_sum([(2, None), (11, None)])
            if not back:
                self.add_classical(from_w2, register, subtract=True)
                self.tight_add(self.a, register, 's1', subtract=True)
                register = self.sigma_in_place_inverse('s0', register)  # W_3
                self.add_classical(classical, register)
            else:
                self.add_classical(classical, register, subtract=True)
                register = self.sigma_in_place('s0', register)
                self.tight_add(self.a, register, 's1')
                self.add_classical(from_w2, register)
            return register
        if not back:
            register = self.sigma_in_place('s1', register)
            self.add_classical(classical, register)
            if s == 23:
                self.tight_add(self.a, register)
        else:
            if s == 23:
                self.tight_add(self.a, register, subtract=True)
            self.add_classical(classical, register, subtract=True)
            register = self.sigma_in_place_inverse('s1', register)
        return register

    def along_chain(self, s: int, register: list, *, back: bool = False) -> list:
        """Turns a register holding W_18 into W_s, for s from 19 to 24; or back."""
        chain = EVEN_CHAIN if s in EVEN_CHAIN else ODD_CHAIN
        steps = chain[:chain.index(s) + 1]
        for step in (reversed(steps) if back else steps):
            register = self.chain_step(step, register, back=back)
        return register

    # ---- computing a schedule word from the base words -------------------------------------

    def classical_part(self, s: int) -> km.array | int:
        return self.classical_sum([term for term in message_inputs(s) if is_classical(term[0])])

    def registers_to_spare(self) -> int:
        """Whole registers that are free now, after the adder's carry qubits."""
        return (self.b.num_free_qubits - CARRY_QUBITS) // WORD

    def add_at_hand(self, s: int, sigma: str | None, target: list) -> None:
        """`target += sigma(W_s)` for W_16, W_18 or a word on a chain, read where it is."""
        if s == 16:
            self.tight_add(self.a, target, sigma)
        elif s == 18:
            self.tight_add(self.c, target, sigma)
        else:
            register = self.along_chain(s, self.c)
            self.tight_add(register, target, sigma)
            self.c = self.along_chain(s, register, back=True)

    def run_add(self, add: tuple, target: list) -> None:
        """Carries out one addition of a plan."""
        kind, p = add[0], add[1]
        if kind == 'hand':
            self.add_at_hand(p, add[2], target)
        elif kind == 'temp':
            register = self.build_word(add[3])
            self.tight_add(register, target, add[2])
            self.measure_word_away(p, register)
        else:  # 'expand': the classical part of W_p, then its quantum inputs.
            self.add_classical(self.classical_part(p), target)
            for inner in add[2]:
                self.run_add(inner, target)

    def build_word(self, plan: tuple) -> list:
        """Carries out a plan. Returns a new register holding the word."""
        b = self.b
        assert plan is not None, 'no plan fits the free registers'
        if plan[0] == 'copy':
            u = plan[1]
            register = list(b.alloc_qubits(WORD))
            b.cx(km.array(self.a if u == 16 else self.c), km.array(register))
            return register if u in (16, 18) else self.along_chain(u, register)
        _, u, seed, seed_plan, adds = plan
        if seed is None:
            register = list(b.alloc_qubits(WORD))
            self.set_words([km.array(register)], [self.classical_part(u)])
        else:
            register = self.build_word(seed_plan)
            if seed[1]:
                register = self.sigma_in_place(seed[1], register)
            self.add_classical(self.classical_part(u), register)
        for add in adds:
            self.run_add(add, register)
        return register

    def stream_step(self, t: int) -> None:
        """Builds W_t in the register of W_(t-7), which already holds sigma1(W_(t-2)) as well."""
        register = self.recent.pop(t - 7)
        p, u = t - 16, t - 15
        if is_classical(p):
            self.add_classical(self.classical_sum([(p, None)]), register)
        elif p in self.kept:
            old = self.kept.pop(p)
            self.tight_add(old, register)
            self.measure_word_away(p, old)
        else:
            self.run_add(plan_add(p, None, self.registers_to_spare())[1], register)
        if is_classical(u):
            self.add_classical(self.classical_sum([(u, 's0')]), register)
        elif u in _CHAIN_COST:
            self.add_at_hand(u, 's0', register)
        else:  # Computed in its own register, and kept: it is the next step's W_(t-16).
            new = self.build_word(plan_word(u, self.registers_to_spare())[1])
            self.tight_add(new, register, 's0')
            self.kept[u] = new
        self.recent[t] = register

    def pass_on_sigma1(self, t: int) -> None:
        """Adds sigma1(W_t) to the register that will become W_(t+2), as soon as W_t exists.

        After that W_t is needed only by its own round, and as the start of W_(t+7).
        """
        if t + 2 <= 63 and t - 5 in self.recent:
            self.tight_add(self.recent[t], self.recent[t - 5], 's1')

    # ---- the header's second block -----------------------------------------------------------

    def one_round(self, t: int, registers: list[km.array], message) -> list[km.array]:
        """Round t. Between schedule steps there is room for an adder's carries."""
        self.w = [None] * 16
        self.w[t % 16] = message if isinstance(message, (int, km.array)) else km.array(message)
        registers = self.round_forward(t, registers)
        self.w = []
        return registers

    def inner2(self, mid: list[km.array], root7: km.array) -> list[km.array]:
        """Returns `compress(mid, root[28:32] ‖ time ‖ bits ‖ nonce ‖ pad640)` in eight fresh words.

        `mid`, `root7` and the nonce are as they were afterwards. Every schedule word that was
        measured away is recorded in `self.owed_words`.
        """
        b = self.b
        work = self.fresh_words(8)
        for source, target in zip(mid, work):
            b.cx(source, target)
        self.borrowed = [mid[0][k] for k in range(WORD - 1)]  # Idle throughout; never an addition's target here.
        self.a = [root7[k] for k in range(WORD)]  # W_0, then W_16.
        self.c = [self.nonce[k] for k in range(WORD)]  # W_3, then W_18.
        self.recent: dict[int, list] = {}
        self.kept: dict[int, list] = {}

        registers = list(work)
        for t in range(16):
            message = self.a if t == 0 else self.c if t == 3 else self.classical_word(t)
            registers = self.one_round(t, registers, message)

        # W_16 = W_0 + sigma0(W_1) + W_9 + sigma1(W_14), and W_18 = W_2 + sigma0(W_3) + W_11 + sigma1(W_16).
        to_w16 = self.classical_sum([(1, 's0'), (9, None), (14, 's1')])
        to_w18 = self.classical_sum([(2, None), (11, None)])
        self.add_classical(to_w16, self.a)
        self.c = self.sigma_in_place('s0', self.c)
        self.tight_add(self.a, self.c, 's1')
        self.add_classical(to_w18, self.c)

        for t in range(16, 64):
            on_chain = None
            if t == 16:
                message = self.a
            elif t == 17:
                message = self.w17
            elif t == 18:
                message = self.c
            elif t in EVEN_CHAIN + ODD_CHAIN and t < 24:
                message = on_chain = self.along_chain(t, self.c)
            else:
                if t < STREAM_FROM:
                    self.recent[t] = self.build_word(plan_word(t, self.registers_to_spare())[1])
                else:
                    self.stream_step(t)
                self.pass_on_sigma1(t)
                message = self.recent[t]
            registers = self.one_round(t, registers, message)
            if on_chain is not None:
                self.c = self.along_chain(t, on_chain, back=True)
            if t + 7 > 63:  # Not the start of a later word: its round was its last use.
                self.measure_word_away(t, self.recent.pop(t))
        assert all(now is then for now, then in zip(registers, work)), 'state registers did not line up'
        for word, offset in zip(work, mid):
            self.add(offset, word, False)

        for s in sorted(self.recent):
            self.measure_word_away(s, self.recent.pop(s))
        for s in sorted(self.kept):
            self.measure_word_away(s, self.kept.pop(s))
        self.add_classical(to_w18, self.c, subtract=True)
        self.tight_add(self.a, self.c, 's1', subtract=True)
        self.c = self.sigma_in_place_inverse('s0', self.c)
        self.add_classical(to_w16, self.a, subtract=True)
        assert ids(self.c) == ids(self.nonce) and ids(self.a) == ids(root7), 'the base words did not return home'
        return work

    def uncompute_inner2(self, work: list[km.array], mid: list[km.array], root7: km.array) -> None:
        """Uncomputes inner2 in `work`, with the schedule in place. `work` ends holding mid.

        `mid` itself is subtracted and then measured away, which makes room for 16 schedule
        words. The phase of that measurement is removed at the end, on the mid in `work`.
        As the schedule is expanded, each W_s passes through its register once: the phase
        owed on it is removed there.
        """
        b = self.b
        for word, offset in zip(work, mid):
            self.add(offset, word, True)
        self.measure_away('mid, during the uncomputation', mid)
        loaded = self.fresh_words(2)
        self.set_words(loaded, [self.time, self.bits])
        assert not self.constants
        self.w = [root7, loaded[0], loaded[1], self.nonce] + list(PAD640)
        for t in range(16, 64):
            self.expand(t)
            if t in self.owed_words:
                bits = self.owed_words.pop(t)
                b.cz(bits, self.w[t % 16])
                b.free(bits)
        registers = list(work)
        for t in reversed(range(64)):
            registers = self.round_backward(t, registers)
            if t >= 16:
                self.contract(t)
        assert all(now is then for now, then in zip(registers, work)), 'state registers did not line up'
        assert not self.constants
        self.set_words(loaded, [self.time, self.bits])
        for register in loaded:
            b.free(register)
        self.w = []
        self.settle('mid, during the uncomputation', work)

    def settle_inner2(self, mid: list[km.array], root7: km.array) -> None:
        """Computes inner2, removes the phase owed on it, and uncomputes it.

        The registers of `mid` are measured away on the way; `mid` is updated to the ones
        that hold it afterwards.
        """
        work = self.inner2(mid, root7)
        self.settle('inner2', work)
        self.uncompute_inner2(work, mid, root7)
        mid[:] = work

    def build(self) -> km.Circuit:
        circuit = super().build()
        assert not self.owed_words, f'phases never removed on schedule words {sorted(self.owed_words)}'
        return circuit


if __name__ == '__main__':
    check_add_classical()
    baseline.main(Builder914, __file__)
