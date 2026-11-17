# Lean lookahead rounds

A circuit for the reaction-depth track. It keeps the approach of
[`../carry-lookahead-rounds`](../carry-lookahead-rounds) (log-depth adders, values kept as
polynomials over qubits, new state words in fresh registers) and removes most of what that
circuit holds in qubits or waits for.

| | This | Carry-lookahead rounds |
|---|---:|---:|
| Qubits (Q) | 826 | 1,006 |
| Reaction depth (D) | 581 | 629 |
| Score (Q × D) | 479,906 | 632,774 |
| Toffolis | 1,888,398 | 1,151,702 |

The score is 24% lower. Most of that is qubits: 180 fewer, against 48 fewer reactions.

## What changed

- **No carry-save row is stored.** A sum of several terms is reduced to two rows by
  carry-save steps. Carry-lookahead rounds wrote down every carry row that was not a
  degree-2 polynomial, 32 qubits each and up to four at a time. Here a carry row is a
  recipe: when a gate needs one of its bits, the bit is built in helper qubits, used and
  unbuilt. That also works when rows are nested, since the helpers of the inner row are
  free again before the outer one is used. It costs Toffolis, not depth.
- **Dropped registers are subtracted away, not measured.** The registers for d and h leave
  the state each round. Before, each was measured in the X basis and the phase fixed on a
  fresh recomputation of its value, which was then uncomputed. Here the recomputation is
  subtracted from the register in place, which leaves it at zero. That needs no second
  register and is one reaction shorter.
- **One fresh register at a time.** A round forms e', clears h, forms a' in the qubits h
  left, and clears d. So the state needs 32 qubits beyond its own, not 64.
- **A prefix network with no carry merged more than four times.** The Sklansky network is
  laid on a 32-wide grid with the first position left empty. A 32-bit addition then has
  AND-depth 5, not 6, and an in-place addition passes its target's phase corrections on to
  the operand in 5 reactions. The rewind of the schedule is a chain of such steps.
- **The adder does the word in two parts.** Bits 0 to 14 first, then the rest, with only the
  carry into bit 15 kept in between. That carry is erased at the end by computing the lower
  carries once more from the sum. In the upper part the product of eight propagate bits is
  held in one qubit, with the tree under it measured away and rebuilt when the product is
  cleared. Together: 26 scratch qubits per addition, not 46.
- **The round constant sits in the schedule register during the round.** K is added into
  the register of W in place before the sum for e' and taken out after h is cleared. It
  saves a level of nested carry rows, and with that about a third of a round's operations.
  So that this does not delay the schedule, W<sub>t+2</sub> is formed before round t.
- **The last two schedule words are never formed.** W<sub>62</sub> and W<sub>63</sub> would
  be the first two steps of the rewind. Their terms go into the sums of rounds 62 and 63
  instead, and the term the rewind starts from, σ1(W<sub>61</sub>), is the outermost row
  when h is cleared in round 63.
- **A rewind step that does not stack phase corrections.** Undoing W<sub>t</sub> subtracts
  three terms. The one the next step depends on is subtracted in place. The other two leave
  through a fresh register, which takes the value W<sub>t−16</sub>, and the old register is
  cleared against it. In the last two steps all three terms go that way.

## Where the depth goes

| Part | Depth |
|---|---:|
| 64 rounds, 7 each (the first one 5) | 446 |
| Last round's phase corrections reach the register of W<sub>61</sub> | 18 |
| Rewind of the schedule: 22 steps of 5 | 110 |
| Last step of the rewind | 7 |
| Total | 581 |

The 7 per round is AND-depth: one level for Ch, one for the last carry-save step, then the
adder's 5. I did not find a way below it with these parts. Every position of the sum has two
late inputs, a bit of e and a bit of Σ1(e), and Σ1 feeds a late bit of e' into every
position, so the top carry has too many late leaves for fewer levels.

The rewind is a chain because undoing W<sub>t</sub> needs W<sub>t−2</sub>, which is undone
next but one. Each step costs one pass through the adder, 5 reactions.

Qubits: 768 for the registers, 32 for the one fresh register, 26 for the adder.

## Tried, and not used

Measured on earlier versions of this circuit.

- **A helper register for d + W + K each round.** It keeps every sum to four terms, but
  costs 32 qubits. With stored carry rows: 909 × 604.
- **Holding d + W + K in the register of W and restoring W from it.** No helper register,
  but the restored word carries the AND-depth of d, and the rewind chains AND-depth from
  word to word: 846 × 726.
- **Forming every schedule word.** 826 × 591.
- **Forming W<sub>t</sub> just before round t**, not two words ahead: 826 × 656.
- **Three in-place subtractions per rewind step:** 826 × 589. With the fresh register in
  every step but none of them taking all three terms: 826 × 585.
- **Clearing and resetting the output of a sum before its carries go in,** so that the phase
  corrections of the forward pass do not reach the carries. No effect on depth.

## Rebuild and verify

`build.py` imports the constants and the hashlib check from `../example/build.py`. It checks
the circuit twice: once as written, and once without its resets, since a reset would hide
scratch that was not cleared.

```bash
uv run --project ../../sha256_verifier python build.py
```

```bash
uv run --project ../../sha256_verifier sha-verify pack circuit.kmb --rm
```

```bash
uv run --project ../../sha256_verifier sha-verify run circuit.kmb.zst
```
