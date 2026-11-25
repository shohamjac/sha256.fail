"""Builds a circuit for the problem `bitcoin-mining-v1` on 914 qubits.

    |extranonce, nonce>  ->  (-1)^f |extranonce, nonce>

This is ../bitcoin-mining-low-qubit (1,072 qubits) with a different header's second block.
There the block held 16 schedule words next to its two states. Here it holds 11 registers
of schedule, and computes the words it does not hold again when they are needed.

It has the layout and the qubit count of ../bitcoin-mining-low-qubit-914, and half its
Toffolis. It does not import that generator.

Only two of the block's 16 message words depend on the search register: W_0, the root's
last word, and W_3, the nonce. Every schedule word is a function of those two, so a word
that is not held can be computed from them, at a cost that grows by about a quarter for
each step further into the schedule.

A schedule step is W_t = W_(t-16) + sigma0(W_(t-15)) + W_(t-7) + sigma1(W_(t-2)).

- Seven registers hold the words in progress. W_t is built in the register of W_(t-7).
  sigma1(W_t) is added to the register that will become W_(t+2) as soon as W_t exists, so
  after its own round W_t is only the start of W_(t+7).
- W_(t-16) and W_(t-15) are too old to be held. Each old word W_u is computed once more,
  in the two registers that are left, and added to the registers that will become
  W_(u+15) and W_(u+16). Those exist for six steps before they are used, so the order in
  which old words are computed is free within that window.
- An old word that stays in its register can be turned into the word two after it, which
  costs far less than computing that word from the base. With two registers only one word
  can stay, because the other register is the workspace. `far_schedule` chooses, by
  dynamic programming over the steps, which words stay and for how long.
- The two base registers do not rest at W_0 and W_3. The nonce's register is turned in
  place into W_19, W_21, W_23 or W_18, W_20, W_22, W_24, and the root word's register
  into W_18 to W_24, whichever is read next, and both go home at the end.
- A planner picks, for the registers free at each moment, the cheapest way to compute a
  word: which input to build on, and whether an input that enters without a sigma is
  computed whole or added term by term, which needs no register for it.

A word measured away leaves a phase. All of them are removed when the block is uncomputed.
Uncomputing does not need the short schedule: mid is subtracted from the result and
measured away, which leaves room for the ordinary 16-word schedule in place, and the rounds
run backwards turn the working state into mid again.

The arithmetic takes what is free at each moment. Kickmix's adder uses every free qubit
as a carry. A Ch or Maj value goes into a temporary when 32 qubits are free and is made in
place when not. A classical addition uses Kickmix's adder when a register is free, and
otherwise the adder of Gidney, "A classical-quantum adder with constant workspace and
linear gates" (arXiv:2507.23079), with two clean qubits and borrowed busy ones. Those two
qubits are the 2 in 914.

Classical message words get qubits only when the schedule overwrites them, in every
compression, and the nine rounds of the header's first block that see only classical data
are done by classical instructions.

Usage, from this directory:

    uv run --project ../../sha256_verifier python build.py
"""

from __future__ import annotations

import functools
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
# The register of the nonce can be turned in place into its neighbours along a path and back;
# 'm' is W_18 without its classical part, sigma0(W_3) + sigma1(W_16):
#
#     W_24 - W_22 - W_20 - W_18 - m - W_3 - W_19 - W_21 - W_23
#
# A plan to put W_u in a new register:
#     ('copy', 16)                     a copy of W_16
#     ('copywalk', u)                  a copy of W_u, after a base register has been turned into it
#     ('build', u, seed, plan, adds)   start from the register `plan` gives for the input `seed`
#                                      (or from the classical part of W_u when `seed` is None),
#                                      then add the other inputs
# A way to add sigma(W_p) to a register:
#     ('hand', p, sigma)               W_p is W_16 or on the path: read it where it is
#     ('temp', p, sigma, plan)         compute W_p by `plan`, add it, measure it away
#     ('expand', p, adds)              no sigma: add the inputs of W_p one by one instead of W_p
#
# Costs are Toffolis. Kickmix's adder takes every free qubit as a carry, up to 30, and costs 61
# less that number. A classical addition costs its width less 2 when a register is free, and
# 3 widths less 5 with only the two carry qubits. The classical parts of everything that is
# added to one register are summed by classical instructions and added once.
#
# A plan counts a walk as if the nonce's register rested at W_18 and went there and back.
# The circuit does better: the register stays where it was last read, and the root word's
# register can take over the even words (see `frame_moves`).

PATH = (24, 22, 20, 18, 'm', 3, 19, 21, 23)
REST = 18
ON_PATH = frozenset({3, 19, 20, 21, 22, 23, 24})
RUN_TIME = frozenset({1, 2, 17})  # Classical words that are known only when the circuit runs.
TO_W18 = ((2, None), (11, None))  # The classical part of W_18.
WALK_WEIGHT = 2.0  # How many times a plan counts a walk from W_18. Of 0.5, 1 and 2, this gave the fewest Toffolis.
FAR_FROM, FAR_TO = 25, 48  # The words that are computed again, each for the step 15 after it.


def classical_terms(s: int) -> tuple:
    return tuple(term for term in message_inputs(s) if is_classical(term[0]))


def classical_width(terms) -> int:
    """How many bits an addition of the sum of these classical words has to touch."""
    value = 0
    for s, name in terms:
        if s in RUN_TIME:
            return WORD
        word = PAD640[s - 4]
        value += low_qubit.sigma_of(word, SIGMA[name]) if name else word
    value &= MASK
    return WORD - ((value & -value).bit_length() - 1) if value else 0


def quantum_add_cost(spare: int) -> int:
    return 31 if spare >= 1 else 61 - CARRY_QUBITS


def classical_add_cost(terms, spare: int) -> int:
    width = classical_width(terms)
    if width <= 1:
        return 0
    return width - 2 if spare >= 1 else 3 * width - 5


def edge_cost(i: int, spare: int) -> int:
    """One step between PATH[i] and PATH[i + 1], in either direction."""
    low, high = PATH[i], PATH[i + 1]
    if high == 'm':
        return classical_add_cost(TO_W18, spare)
    if low == 'm':
        return quantum_add_cost(spare)
    if low == 3:
        return classical_add_cost(classical_terms(19), spare)
    s = max(low, high)
    return classical_add_cost(classical_terms(s), spare) + (quantum_add_cost(spare) if s == 23 else 0)


A_WORDS = (16, 18, 20, 22, 24)  # What the register of the root's last word can hold.


def frame_moves(frame: tuple, spare: int) -> list[tuple]:
    """The single steps from a frame (the words in the two base registers), each with its cost.

    The root word's register holds W_16 at rest. While the nonce's register is on the odd
    side (W_3, W_19 or W_21), it can become W_18 = sigma1(W_16) + sigma0(W_3) + classical
    words instead, and walk on to W_20, W_22 and W_24. Then even and odd words are at hand
    together. Only W_16 and W_23 are out of reach until it is back.
    """
    a_word, c_word = frame
    moves = []
    i = PATH.index(c_word)
    for j in (i - 1, i + 1):
        if 0 <= j < len(PATH):
            low = min(i, j)
            if a_word == 16 or (PATH[low], PATH[low + 1]) in ((3, 19), (19, 21)):
                moves.append(((a_word, PATH[j]), ('c', low, j > i), edge_cost(low, spare)))
    i = A_WORDS.index(a_word)
    for j in (i - 1, i + 1):
        if 0 <= j < len(A_WORDS):
            low, high = sorted((a_word, A_WORDS[j]))
            if low == 16:
                if c_word != 3:
                    continue
                cost = quantum_add_cost(spare) + classical_add_cost(TO_W18, spare)
            else:
                cost = classical_add_cost(classical_terms(high), spare)
            moves.append(((A_WORDS[j], c_word), ('a', high, A_WORDS[j] == high), cost))
    return moves


def frame_route(frame: tuple, wanted, spare: int) -> tuple[float, list, tuple]:
    """The cheapest moves from `frame` to a frame for which `wanted(frame)` holds."""
    best = {frame: (0.0, [])}
    queue = [frame]
    while queue:
        queue.sort(key=lambda f: best[f][0])
        here = queue.pop(0)
        cost, moves = best[here]
        if wanted(here):
            return cost, moves, here
        for there, move, price in frame_moves(here, spare):
            price += cost + 0.01  # Among equal routes, the one with fewer steps.
            if price < best.get(there, (float('inf'),))[0]:
                best[there] = (price, moves + [move])
                if there not in queue:
                    queue.append(there)
    raise ValueError(f'no route from {frame}')


def walk_cost(stop, spare: int) -> int:
    i, j = sorted((PATH.index(REST), PATH.index(stop)))
    return sum(edge_cost(k, spare) for k in range(i, j))


@functools.lru_cache(maxsize=None)
def plan_word(u: int, registers: int) -> tuple[float, tuple | None]:
    """The cheapest plan for W_u in at most `registers` registers, its own included."""
    registers = min(registers, 9)
    if registers < 1 or u < 16:
        return float('inf'), None
    if u == 16:
        return 0, ('copy', 16)
    if u == REST or u in ON_PATH:
        return WALK_WEIGHT * walk_cost(u, registers), ('copywalk', u)
    best: tuple[float, tuple | None] = (float('inf'), None)
    for seed in [*quantum_inputs(u), None]:
        cost, plan = (0, None) if seed is None else plan_word(seed[0], registers)
        constants = list(classical_terms(u))
        adds = []
        for term in quantum_inputs(u):
            if term != seed:
                term_cost, term_constants, add = plan_term(term[0], term[1], registers - 1)
                cost += term_cost
                constants += term_constants
                adds.append(add)
        if seed is not None:
            cost += classical_add_cost(constants, registers - 1)
        if cost < best[0]:
            best = (cost, ('build', u, seed, plan, tuple(adds)))
    return best


@functools.lru_cache(maxsize=None)
def plan_term(p: int, sigma: str | None, spare: int) -> tuple[float, tuple, tuple | None]:
    """The cheapest way to add sigma(W_p) to a register with `spare` registers free.

    Returns the cost, the classical words that are left to be added, and the plan.
    """
    spare = max(0, min(spare, 9))
    if p == 16:
        return quantum_add_cost(spare), (), ('hand', p, sigma)
    best: tuple[float, tuple, tuple | None] = (float('inf'), (), None)
    if p == REST or p in ON_PATH:
        best = (WALK_WEIGHT * walk_cost(p, spare) + quantum_add_cost(spare), (), ('hand', p, sigma))
    if spare >= 1 and p >= 16:
        cost, plan = plan_word(p, spare)
        cost += quantum_add_cost(spare - 1)
        if cost < best[0]:
            best = (cost, (), ('temp', p, sigma, plan))
    if sigma is None and p >= 19:
        cost, constants, adds = 0, list(classical_terms(p)), []
        for q, name in quantum_inputs(p):
            term_cost, term_constants, add = plan_term(q, name, spare)
            cost += term_cost
            constants += term_constants
            adds.append(add)
        if cost < best[0]:
            best = (cost, tuple(constants), ('expand', p, tuple(adds)))
    return best


def bracket_cost(u: int, spare: int) -> float:
    """Turning a register that holds W_(u-2) into W_u, with `spare` registers free."""
    cost, constants = 0, list(classical_terms(u))
    for p, sigma in quantum_inputs(u):
        if (p, sigma) != (u - 2, 's1'):
            term_cost, term_constants, _ = plan_term(p, sigma, spare)
            cost += term_cost
            constants += term_constants
    return cost + classical_add_cost(constants, spare)


def free_registers(step: int) -> int:
    """Registers free for recomputing when step `step` starts: a word in progress dies after round 57."""
    return 2 + max(0, step - 57)


def round_extra(spare: int) -> int:
    """What a round and the addition before it cost more with fewer than two registers free."""
    return 0 if spare >= 2 else 56 if spare == 1 else 293 + 28


@functools.lru_cache(maxsize=None)
def far_schedule() -> dict[int, tuple]:
    """When each of W_25..W_48 is computed again, how, and which stay in a register.

    W_u is added to the registers of W_(u+15) and W_(u+16), which exist from step u + 10
    to step u + 15. A word that stays (a walker) is later turned into the word two after
    it, which costs much less than computing that word from the base. With two registers
    free only one word can stay, because the other register is the workspace.

    Returns, for each step, its actions in order: `('step', u, keep)` turns the walker
    W_(u-2) into W_u, `('scratch', u, keep)` computes W_u from the base, `('drop', u)`
    measures the walker W_u away.
    """
    start = (FAR_FROM - 1 if FAR_FROM % 2 else FAR_FROM - 2, FAR_FROM - 2 if FAR_FROM % 2 else FAR_FROM - 1, frozenset())
    states: dict[tuple, tuple[float, tuple]] = {start: (0, ())}
    for step in range(FAR_FROM + 10, 64):
        registers = free_registers(step)
        queue = sorted(states, key=lambda state: state[0] + state[1])
        while queue:
            state = queue.pop(0)
            even, odd, walkers = state
            cost, actions = states[state]
            moves = [((even, odd, walkers - {w}), cost, actions + ((step, 'drop', w),)) for w in walkers]
            for u in (even + 2, odd + 2):
                if u > FAR_TO or u + 10 > step:
                    continue
                served = (u, odd) if u % 2 == 0 else (even, u)
                uses = 2 if u + 16 <= 63 else 1
                spare = registers - len(walkers)
                if u - 2 in walkers:
                    price = cost + bracket_cost(u, spare) + uses * quantum_add_cost(spare)
                    for keep in (True, False):
                        left = walkers - {u - 2} | ({u} if keep else set())
                        moves.append((served + (frozenset(left),), price, actions + ((step, 'step', u, keep),)))
                price = cost + plan_word(u, spare)[0] + uses * quantum_add_cost(spare - 1)
                for keep in (True, False):
                    left = walkers | ({u} if keep else set())
                    moves.append((served + (frozenset(left),), price, actions + ((step, 'scratch', u, keep),)))
            for new, price, new_actions in moves:
                if price < states.get(new, (float('inf'),))[0]:
                    states[new] = (price, new_actions)
                    queue.append(new)
                    queue.sort(key=lambda state: state[0] + state[1])
        after = {}
        for (even, odd, walkers), (cost, actions) in states.items():
            due = min(FAR_TO, step - 15)
            spare = registers - len(walkers)
            if spare < 0 or even < due - due % 2 or odd < due - (1 - due % 2):
                continue
            after[(even, odd, walkers)] = (cost + round_extra(spare), actions)
        states = after
    done = FAR_TO - FAR_TO % 2, FAR_TO - (1 - FAR_TO % 2)
    cost, actions = min((value for state, value in states.items() if state[:2] == done), key=lambda value: value[0])
    schedule: dict[int, list] = {}
    for step, *action in actions:
        schedule.setdefault(step, []).append(tuple(action))
    return {step: tuple(actions) for step, actions in schedule.items()}


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


def known(word) -> bool:
    """Whether a word is a constant or classical bits, and so needs no qubits."""
    return isinstance(word, int) or isinstance(word[0], km.b)


class Builder914(low_qubit.LowQubitBuilder):
    """`LowQubitBuilder` with a header's second block that holds 11 schedule words."""

    def __init__(self) -> None:
        super().__init__()
        b = self.b
        b.set_max_qubits(QUBITS)
        self.one = b.alloc_bits(1)[0]
        b.bit_store(self.one, True)
        self.sums: dict[tuple, km.array | int] = {}
        self.owed_words: dict[int, km.array] = {}  # XOR of the measured bits of every W_s measured away.
        self.borrowed: list | None = None  # Busy qubits a classical addition may borrow, in the header's second block.
        self.w17 = self.classical_sum([(1, None), (2, 's0'), (10, None), (15, 's1')])

    # ---- every compression: Sigma, Ch and Maj with what is free ----------------------------
    #
    # The base class always writes a Sigma, Ch or Maj value into a 32-qubit temporary. Here a
    # Sigma value is made in place. A Ch or Maj value goes into a temporary when 32 qubits
    # are free, because its ANDs are then erased by measurement, and is made in place when
    # they are not, as ../zero-scratch does. Kickmix's adder uses what is left for carries.

    def add_linear(self, source: km.array, sigma, target: km.array, subtract: bool) -> None:
        """`target += sigma(source)`, with `source` turned into sigma(source) by CNOTs and back."""
        self.qadd([source[k] for k in range(WORD)], target, BIG_SIGMA_NAME.get(sigma), subtract)

    def add_ch(self, e: km.array, f: km.array, g: km.array, target: km.array, subtract: bool) -> None:
        """`target += Ch(e, f, g)`, with Ch = g ^ (e & (f ^ g))."""
        b = self.b
        b.cx(g, f)
        if b.num_free_qubits >= WORD:
            value = b.alloc_qubits(WORD)
            b.init_and(e, f, value), b.cx(g, value)
            self.add(value, target, subtract)
            b.cx(g, value), b.del_and(e, f, value)  # Measured away; costs no Toffoli.
            b.free(value)
        else:
            b.ccx(e, f, g)
            self.add(g, target, subtract)
            b.ccx(e, f, g)
        b.cx(g, f)

    def add_maj(self, a: km.array, b_: km.array, c: km.array, target: km.array, subtract: bool) -> None:
        """`target += Maj(a, b, c)`, with Maj = c ^ ((a ^ c) & (b ^ c))."""
        b = self.b
        b.cx(c, a), b.cx(c, b_)
        if b.num_free_qubits >= WORD:
            value = b.alloc_qubits(WORD)
            b.init_and(a, b_, value), b.cx(c, value)
            self.add(value, target, subtract)
            b.cx(c, value), b.del_and(a, b_, value)
            b.free(value)
        else:
            b.ccx(a, b_, c)
            self.add(c, target, subtract)
            b.ccx(a, b_, c)
        b.cx(c, b_), b.cx(c, a)

    def add_round_constant_and_message(self, t: int, target: km.array, subtract: bool) -> None:
        """`target += K_t + W_t`, as one addition when W_t is classical."""
        message = self.w[t % 16]
        constant = self.classical_plus(message, K[t]) if known(message) else K[t]
        if self.b.num_free_qubits >= WORD:
            self.add_value(constant, target, subtract)
        else:
            self.cadd(constant, [target[k] for k in range(WORD)], subtract)
        if not known(message):
            self.add_value(message, target, subtract)

    # ---- every compression: classical words get qubits only when the schedule overwrites them ----
    #
    # The base class does this for the padding, which is constant. Here it also holds for
    # the words that are classical bits: the coinbase tail, the version, the previous hash,
    # time and bits. Until W_t overwrites such a word, it and everything classical that is
    # added to it are summed by classical instructions. Rounds that see only classical data
    # are done by classical instructions too.

    def open_window(self, window) -> None:
        assert not self.constants
        self.w = list(window.words)
        self.totals: dict[int, km.array | int] = {}
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

    def schedule_terms(self, t: int) -> tuple[km.array | int, list]:
        """What is added to W_(t-16) to make W_t: the sum of its classical part, and the quantum terms."""
        w = self.w
        terms = [(w[(t - 15) % 16], SIGMA['s0']), (w[(t - 7) % 16], None), (w[(t - 2) % 16], SIGMA['s1'])]
        if t not in self.totals:
            total = 0
            for word, sigma in terms:
                if known(word):
                    total = self.classical_plus(total, self.classical_of(word, sigma))
            self.totals[t] = total
        return self.totals[t], [term for term in terms if not known(term[0])]

    def expand(self, t: int) -> None:
        """Turns W_(t-16) into W_t in place. A classical W_(t-16) gets its qubits here."""
        position = t % 16
        total, quantum = self.schedule_terms(t)
        if known(self.w[position]):
            value = self.classical_plus(self.w[position], total)
            self.constants[position] = (self.w[position], value)
            self.w[position] = self.b.alloc_qubits(WORD)
            self.set_words([self.w[position]], [value])
        else:
            self.add_value(total, self.w[position], False)
        for word, sigma in quantum:
            self.add_sigma(word, sigma, self.w[position], False)

    def contract(self, t: int) -> None:
        """Turns W_t back into W_(t-16)."""
        position = t % 16
        target = self.w[position]
        total, quantum = self.schedule_terms(t)
        for word, sigma in reversed(quantum):
            self.add_sigma(word, sigma, target, True)
        if t < 32 and position in self.constants:
            self.w[position], value = self.constants.pop(position)
            self.set_words([target], [value])
            self.b.free(target)
        else:
            self.add_value(total, target, True)

    def classical_start(self, start: list, window) -> tuple[int, list]:
        """How many leading rounds see only classical data, and the state after them."""
        skip, state = 0, list(start)
        while skip < 16 and known(window.words[skip]):
            state = self.classical_round(skip, state, window.words[skip])
            skip += 1
        return skip, state

    def compute(self, start: list, window, *, settle: str | None = None, then: str = 'rewind') -> list[km.array]:
        """`LowQubitBuilder.compute`, starting after the rounds that are classical."""
        skip, begin = self.classical_start(start, window)
        state = self.fresh_words(8)
        registers = [state[(i - skip) % 8] for i in range(8)]  # As `skip` rounds would have left them.
        self.set_words(registers, begin)
        self.open_window(window)
        for t in range(skip, 64):
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

    def uncompute(self, state: list[km.array], start: list, window, *, expanded: bool = False,
                  settle: str | None = None) -> None:
        """Runs `compute` backwards and frees `state`."""
        skip, begin = self.classical_start(start, window)
        if not expanded:
            self.open_window(window)
            for t in range(16, 64):
                self.expand(t)
        if settle is not None:
            self.settle(settle, self.w)
        for word, offset in zip(state, start):
            self.add(offset, word, True)
        registers = list(state)
        for t in reversed(range(skip, 64)):
            registers = self.round_backward(t, registers)
            if t >= 16:
                self.contract(t)
        self.close_window(window)
        self.set_words(registers, begin)
        for word in state:
            self.b.free(word)

    def coinbase_window(self):
        """extranonce ‖ tail, on a copy of the extranonce; the tail stays classical."""
        fresh = self.fresh_words(2)
        values = [self.extranonce[0:32], km.array(list(self.tail[0:16]) + list(self.extranonce[32:48]))]
        return low_qubit.Window(fresh + self.words(self.tail[16:]), lambda: self.set_words(fresh, values), fresh)

    def header_window_1(self, root: list[km.array]):
        """version ‖ prev_hash ‖ root[0:28], the root's first seven words in place."""
        return low_qubit.Window([self.version] + self.words(self.prev_hash) + root[0:7], lambda: None, [])

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

    def classical_sum(self, terms) -> km.array | int:
        """The sum of classical words, each with a sigma applied or not: a constant, or 32 bits."""
        constant, variable = 0, []
        for s, name in terms:
            word = self.classical_word(s)
            if isinstance(word, int):
                constant += low_qubit.sigma_of(word, SIGMA[name]) if name else word
            else:
                variable.append((s, name))
        return self.sum_of(tuple(sorted(variable, key=str)), constant & MASK)

    def sum_of(self, variable: tuple, constant: int) -> km.array | int:
        """`constant` plus the run-time words in `variable`. Partial sums are shared."""
        key = (variable, constant)
        if key not in self.sums:
            if not variable:
                total = constant
            elif constant:
                total = self.classical_add(self.sum_of(variable, 0), constant)
            elif len(variable) == 1:
                (s, name), = variable
                word = self.classical_word(s)
                total = self.classical_sigma(word, SIGMA[name]) if name else word
            else:
                total = self.classical_add(self.sum_of(variable[:-1], 0), self.sum_of(variable[-1:], 0))
            self.sums[key] = total
        return self.sums[key]

    def classical_of(self, word: km.array | int, sigma) -> km.array | int:
        """sigma(word), or the word itself when `sigma` is None, for a constant or classical bits."""
        if sigma is None:
            return word
        return low_qubit.sigma_of(word, sigma) if isinstance(word, int) else self.classical_sigma(word, sigma)

    def classical_plus(self, x: km.array | int, y: km.array | int) -> km.array | int:
        if isinstance(x, int) and isinstance(y, int):
            return (x + y) & MASK
        if isinstance(x, int):
            x, y = y, x
        if isinstance(y, int) and not y & MASK:
            return x
        return self.classical_add(x, y & MASK if isinstance(y, int) else y)

    def classical_xor(self, x: km.array | int, y: km.array | int) -> km.array | int:
        if isinstance(x, int) and isinstance(y, int):
            return x ^ y
        out = self.zero_bits(WORD)
        for value in (x, y):
            if isinstance(value, int):
                for k in range(WORD):
                    if value >> k & 1:
                        self.b.cx(self.one, out[k])
            else:
                self.b.cx(value, out)
        return out

    def classical_and(self, x: km.array | int, y: km.array | int) -> km.array | int:
        if isinstance(x, int) and isinstance(y, int):
            return x & y
        if isinstance(y, int):
            x, y = y, x
        out = self.zero_bits(WORD)
        for k in range(WORD):
            if isinstance(x, int):
                if x >> k & 1:
                    self.b.cx(y[k], out[k])
            else:
                self.b.push_condition(x[k])
                self.b.cx(y[k], out[k])
                self.b.pop_condition()
        return out

    def classical_round(self, t: int, state: list, message: km.array | int) -> list:
        """One round on a state of constants and classical bits."""
        a, b_, c, d, e, f, g, h = state
        plus, xor, both = self.classical_plus, self.classical_xor, self.classical_and
        ch = xor(g, both(e, xor(f, g)))
        maj = xor(c, both(xor(a, c), xor(b_, c)))
        t1 = plus(plus(plus(plus(h, self.classical_of(e, low_qubit.BIG_SIGMA1)), ch), K[t]), message)
        t2 = plus(self.classical_of(a, low_qubit.BIG_SIGMA0), maj)
        return [plus(t1, t2), a, b_, c, plus(d, t1), e, f, g]

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
        out, carry, both, following = self.zero_bits(WORD), self.zero_bits(1)[0], self.zero_bits(1)[0], self.zero_bits(1)[0]

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
            xor(both, x[i]), xor(both, yi)
            xor(out[i], both), xor(out[i], carry)
            xor_and(following, x[i], yi), xor_and(following, carry, both)  # maj(x, y, carry) = x y xor carry (x xor y)
            b.bit_store(km.array([carry, both]), False)
            carry, following = following, carry
        b.free(km.array([carry, both, following]))
        return out

    # ---- arithmetic on registers given as lists of qubits ------------------------------------

    def qadd(self, source: list, target, sigma: str | None = None, subtract: bool = False) -> None:
        """`target += sigma(source)`, or `-=`. The adder takes its carries from the free qubits."""
        turned = self.sigma_in_place(sigma, source) if sigma else source
        self.add(km.array(turned), target if isinstance(target, km.array) else km.array(target), subtract)
        if sigma:
            self.sigma_in_place_inverse(sigma, turned)

    def cadd(self, value: km.array | int, target: list, subtract: bool = False) -> None:
        """`target += value`, or `-=`, for a constant or 32 classical bits."""
        b = self.b
        if isinstance(value, int):
            value &= MASK
            if not value:
                return
            low = (value & -value).bit_length() - 1  # Zeros at the bottom change nothing below them.
            value, target = value >> low, target[low:]
            if len(target) == 1:
                b.x(target[0])
                return
            bits = [value >> k & 1 for k in range(len(target))]
        else:
            bits = [value[k] for k in range(WORD)]
        if b.num_free_qubits >= len(target):
            self.add(value, km.array(target), subtract)
        else:  # b - a = not(not b + a)
            if subtract:
                b.x(km.array(target))
            add_classical(b, bits, target, self.borrowed)
            if subtract:
                b.x(km.array(target))

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

    # ---- the words that the nonce's register can be turned into ----------------------------

    def path_step(self, register: list, i: int, forward: bool) -> list:
        """Turns PATH[i] into PATH[i + 1] in place, or back when `forward` is not set."""
        low, high = PATH[i], PATH[i + 1]
        if high == 'm':
            self.cadd(self.classical_sum(TO_W18), register, subtract=forward)
        elif low == 'm':  # W_18 = sigma0(W_3) + sigma1(W_16) + its classical part.
            if forward:
                self.qadd(self.a, register, 's1', subtract=True)
                register = self.sigma_in_place_inverse('s0', register)
            else:
                register = self.sigma_in_place('s0', register)
                self.qadd(self.a, register, 's1')
        elif low == 3:  # W_19 = W_3 + its classical part.
            self.cadd(self.classical_sum(classical_terms(19)), register, subtract=not forward)
        else:  # W_s = sigma1(W_(s-2)) + its classical part, plus W_16 for s = 23.
            s = max(low, high)
            if (high == s) == forward:
                register = self.sigma_in_place('s1', register)
                self.cadd(self.classical_sum(classical_terms(s)), register)
                if s == 23:
                    self.qadd(self.a, register)
            else:
                if s == 23:
                    self.qadd(self.a, register, subtract=True)
                self.cadd(self.classical_sum(classical_terms(s)), register, subtract=True)
                register = self.sigma_in_place_inverse('s1', register)
        return register

    def a_step(self, s: int, up: bool) -> None:
        """Turns the root word's register from W_(s-2) into W_s, or back. The nonce's register holds W_3 for s = 18."""
        classical = self.classical_sum(TO_W18 if s == 18 else classical_terms(s))
        if up:
            self.a = self.sigma_in_place('s1', self.a)
            if s == 18:
                self.qadd(self.c, self.a, 's0')
            self.cadd(classical, self.a)
        else:
            self.cadd(classical, self.a, subtract=True)
            if s == 18:
                self.qadd(self.c, self.a, 's0', subtract=True)
            self.a = self.sigma_in_place_inverse('s1', self.a)

    def move_frame(self, wanted) -> None:
        """Takes the two base registers by the cheapest route to a frame that `wanted` accepts."""
        _, moves, self.frame = frame_route(self.frame, wanted, self.registers_to_spare())
        for register, where, forward in moves:
            if register == 'c':
                self.c = self.path_step(self.c, where, forward)
            else:
                self.a_step(where, forward)

    def reach(self, word: int) -> list:
        """Returns a register holding `word`, after turning the base registers into it if needed."""
        self.move_frame(lambda frame: word in frame)
        return self.a if self.frame[0] == word else self.c

    # ---- computing a schedule word from the base words -------------------------------------

    def registers_to_spare(self) -> int:
        """Whole registers that are free now, after the two carry qubits."""
        return (self.b.num_free_qubits - CARRY_QUBITS) // WORD

    def flatten(self, adds, constants: list) -> list:
        """The additions of a plan with every 'expand' opened; their classical words go to `constants`."""
        leaves = []
        for add in adds:
            assert add is not None, 'no plan fits the free registers'
            if add[0] == 'expand':
                constants.extend(classical_terms(add[1]))
                leaves += self.flatten(add[2], constants)
            else:
                leaves.append(add)
        return leaves

    def add_leaves(self, leaves: list, target: list) -> None:
        """Carries out additions to one register: words at hand in one walk each way, then the rest."""
        hands = [leaf for leaf in leaves if leaf[0] == 'hand']
        wanted = {p for _, p, _ in hands}
        while wanted:  # The nearest word first.
            self.move_frame(lambda frame: wanted & set(frame))
            for word in wanted & set(self.frame):
                register = self.a if self.frame[0] == word else self.c
                for _, p, sigma in hands:
                    if p == word:
                        self.qadd(register, target, sigma)
                wanted.discard(word)
        for leaf in leaves:
            if leaf[0] == 'temp':
                register = self.build_word(leaf[3])
                self.qadd(register, target, leaf[2])
                self.measure_word_away(leaf[1], register)

    def add_terms(self, terms: list, target: list, constants: list) -> None:
        """`target += ` the quantum `terms` and the classical `constants`, planned for what is free now."""
        spare = self.registers_to_spare()
        constants = list(constants)
        leaves = self.flatten([plan_term(p, sigma, spare)[2] for p, sigma in terms], constants)
        self.cadd(self.classical_sum(constants), target)
        self.add_leaves(leaves, target)

    def build_word(self, plan: tuple) -> list:
        """Carries out a plan. Returns a new register holding the word."""
        b = self.b
        assert plan is not None, 'no plan fits the free registers'
        if plan[0] in ('copy', 'copywalk'):  # The walk comes first: it has one more register free than the copy would.
            source = self.reach(plan[1])
            register = list(b.alloc_qubits(WORD))
            b.cx(km.array(source), km.array(register))
            return register
        _, u, seed, seed_plan, adds = plan
        constants = list(classical_terms(u))
        leaves = self.flatten(adds, constants)
        if seed is None:
            register = list(b.alloc_qubits(WORD))
            self.set_words([km.array(register)], [self.classical_sum(constants)])
        else:
            register = self.build_word(seed_plan)
            if seed[1]:
                register = self.sigma_in_place(seed[1], register)
            self.cadd(self.classical_sum(constants), register)
        self.add_leaves(leaves, register)
        return register

    def serve(self, step: int) -> None:
        """Carries out what `far_schedule` puts at this step."""
        for kind, u, *keep in far_schedule().get(step, ()):
            if kind == 'drop':
                self.measure_word_away(u, self.walkers.pop(u))
                continue
            if kind == 'step':  # W_u = sigma1(W_(u-2)) + the rest.
                register = self.sigma_in_place('s1', self.walkers.pop(u - 2))
                self.add_terms([term for term in quantum_inputs(u) if term != (u - 2, 's1')], register, classical_terms(u))
            else:
                register = self.build_word(plan_word(u, self.registers_to_spare())[1])
            self.qadd(register, self.recent[u + 8], 's0')  # The register that becomes W_(u+15).
            if u + 16 <= 63:
                self.qadd(register, self.recent[u + 9])
            self.served.add(u)
            if keep[0]:
                self.walkers[u] = register
            else:
                self.measure_word_away(u, register)

    def fresh_stream_word(self, t: int) -> list:
        """W_t in a new register, for the steps before there is a W_(t-7) to build on."""
        if t - 2 not in self.recent:
            return self.build_word(plan_word(t, self.registers_to_spare())[1])
        spare = self.registers_to_spare() - 1
        constants = list(classical_terms(t))
        others = [term for term in quantum_inputs(t) if term != (t - 2, 's1')]
        leaves = self.flatten([plan_term(p, sigma, spare)[2] for p, sigma in others], constants)
        register = list(self.b.alloc_qubits(WORD))
        self.set_words([km.array(register)], [self.classical_sum(constants)])
        self.qadd(self.recent[t - 2], register, 's1')
        self.add_leaves(leaves, register)
        return register

    def stream_step(self, t: int) -> None:
        """Builds W_t in the register of W_(t-7), which already holds sigma1(W_(t-2)) as well.

        What is missing is W_(t-16) + sigma0(W_(t-15)). When W_(t-15) has to be computed, it is
        also added to the register of the next step, which needs it as its W_(t-16).
        """
        self.serve(t)
        target = self.recent.pop(t - 7)
        u = t - 15
        terms, constants = [], []
        for term in [(t - 16, None), (u, 's0')]:
            if term[0] in self.served or (term[0] == t - 16 and t in self.preadded):
                continue
            (constants if is_classical(term[0]) else terms).append(term)
        computed = (u, 's0') in terms and plan_term(u, 's0', self.registers_to_spare())[2][0] == 'temp'
        if computed:
            terms.remove((u, 's0'))
        self.add_terms(terms, target, constants)
        if computed:
            register = self.build_word(plan_word(u, self.registers_to_spare())[1])
            self.qadd(register, target, 's0')
            self.qadd(register, self.recent[t - 6])
            self.preadded.add(t + 1)
            self.measure_word_away(u, register)
        self.recent[t] = target

    def pass_on_sigma1(self, t: int) -> None:
        """Adds sigma1(W_t) to the register that will become W_(t+2), as soon as W_t exists.

        After that W_t is needed only by its own round, and as the start of W_(t+7).
        """
        if t + 2 <= 63 and t - 5 in self.recent:
            self.qadd(self.recent[t], self.recent[t - 5], 's1')

    # ---- the header's second block -----------------------------------------------------------

    def one_round(self, t: int, registers: list[km.array], message) -> list[km.array]:
        """Round t. Between schedule steps the registers for recomputing are free."""
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
        self.c = [self.nonce[k] for k in range(WORD)]  # W_3, then whichever word of the path was read last.
        self.frame = (16, 3)  # The words in `a` and `c`, once W_0 has become W_16.
        self.recent: dict[int, list] = {}  # The registers of the words in progress.
        self.walkers: dict[int, list] = {}  # Recomputed words that are kept.
        self.preadded: set[int] = set()  # Steps whose W_(t-16) is already in their register.
        self.served: set[int] = set()  # Words that `serve` has added where they are needed.

        registers = list(work)
        for t in range(16):
            message = self.a if t == 0 else self.c if t == 3 else self.classical_word(t)
            registers = self.one_round(t, registers, message)

        to_w16 = self.classical_sum([(1, 's0'), (9, None), (14, 's1')])  # W_16 = W_0 + this.
        self.cadd(to_w16, self.a)

        for t in range(16, 64):
            if t == 17:
                message = self.w17
            elif t < 24:
                message = self.reach(t)
            else:
                if t - 7 in self.recent:
                    self.stream_step(t)
                else:
                    self.recent[t] = self.fresh_stream_word(t)
                self.pass_on_sigma1(t)
                message = self.recent[t]
            registers = self.one_round(t, registers, message)
            if t + 7 > 63:  # Not the start of a later word: its round was its last use.
                self.measure_word_away(t, self.recent.pop(t))
        assert all(now is then for now, then in zip(registers, work)), 'state registers did not line up'
        assert not self.recent, sorted(self.recent)
        for word, offset in zip(work, mid):
            self.add(offset, word, False)

        for u in sorted(self.walkers):
            self.measure_word_away(u, self.walkers.pop(u))
        self.move_frame(lambda frame: frame == (16, 3))
        self.cadd(to_w16, self.a, subtract=True)
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
        assert not self.constants
        self.w = [root7, self.time, self.bits, self.nonce] + list(PAD640)
        self.totals = {}
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
