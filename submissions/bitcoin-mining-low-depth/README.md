# Lookahead rounds, states measured away

A phase oracle for the problem `bitcoin-mining-v1`, built for the reaction-depth track. The
contract is [bitcoin-mining-v1.md](../../sha256_verifier/docs/bitcoin-mining-v1.md).

| | This | [Baseline](../bitcoin-mining-baseline) |
|---|---:|---:|
| Qubits (Q) | 1,249 | 2,000 |
| Reaction depth (D) | 4,435 | 108,224 |
| Score on the depth track (Q × D) | 5,539,315 | 216,448,000 |
| Toffolis | 7,575,806 | 262,158 |
| Operations | 17,484,731 | 3,526,903 |

The depth-track score is 39 times lower. Toffolis are not scored on this track and the
circuit spends them freely: it is no entry for the Toffoli track.

Verified at full strength before it was written up: 2,848 shots on 16 real blocks and
1,048,576 random shots with a random salt, all correct.

## How it works

- **Rounds from [Lean lookahead rounds](../lean-lookahead-rounds).** A round forms the new
  e and a in fresh registers, through carry-save steps and an adder of AND-depth 5, and
  clears the two registers it drops by subtracting a recomputation in place. That costs 7
  reactions per round. Undoing a round costs 7 as well: the registers it clears pass their
  phase corrections on to the words the next step clears.
- **A chaining value that is not needed is measured away.** The five compressions form a
  chain, and undoing one needs the output of the one before. The baseline holds all five
  outputs to the end. Here a schedule window, with the chaining value inside it, is measured
  in the X basis as soon as its compression is done, and the measured bits are kept. The
  phase this leaves is cancelled with Z gates when the same value is computed again on the
  way back. A value computed again starts from the search register, so it is no deeper than
  the first time: the second computation costs operations and no depth.
- **What is held.** Next to the compression it is working on (a 512-qubit schedule window,
  a 256-qubit state and scratch), the circuit holds at most two chaining values: the
  header's midstate and the last word of the merkle root while the block hash is computed
  and undone, and inner1 while the header's first block is undone.
- **Twelve passes of 64 rounds in under 20,000,000 operations.** That is the limit of the
  problem, and the lean rounds, at 53,000 operations each, would need 40 million. So the
  adder keeps the products of its propagate bits in qubits and measures them away after
  use, and a carry-save row is written down once, not rebuilt for each gate that reads it.
  The terms of e' that are ready early are added up in a helper register. One carry-save
  step is then left for Σ1 and Ch, and the helper itself, with those two XORed in, is the
  adder's operand. A round is about 17,000 operations with the wide adder and 21,000 with
  the narrow one.
- **A narrow adder where it matters.** In the passes that set the qubit count, the adder
  does the word in two parts and keeps one carry between them, as the lean adder does. It
  needs 49 scratch qubits, not 80, and 1,004 operations, not 732.
- **Classical inputs are qubits of depth zero.** They are XORed in under classical
  conditions. The first nine rounds of the header's first block see only classical words,
  so they add nothing to the depth, with no classical arithmetic in the circuit.
- **Where a digest is handed on.** The first round that reads a digest takes its first word
  before the feed-forward is added, and adds the word last. Over the circuit this saves 70
  reactions.
- **The last compression stops early.** Only H<sub>5</sub>, H<sub>6</sub> and H<sub>7</sub>
  are compared, so it runs 63 rounds and forms no new a in the last four.
- **The comparison is a phase.** `v < T` exactly when `~v + T` carries out of the top bit.
  The 96 bits are done in three chunks with the adder's prefix network, the target's bits
  entering as classical conditions.

## Where the depth goes

| Part | Depth after it |
|---|---:|
| coinbase's last block → inner1 | 612 |
| second hash → merkle root | 944 |
| header, first block (55 rounds count) | 1,334 |
| header, second block | 1,787 |
| second hash → the three compared words (63 rounds) | 2,227 |
| comparison and phase | 2,227 |
| undo the block hash | 2,667 |
| undo the header's second block | 3,131 |
| compute inner1 and the merkle root again | 3,131 |
| undo the header's first block | 3,587 |
| undo the merkle root | 3,971 |
| undo the coinbase block | 4,435 |

The 310 rounds on the longest chain account for 4,340 of it at 7 forward and 7 back. The
rest is the hand-overs between compressions and the comparison.

Qubits at the peak: 80 in the search register, 288 in the two held values, 512 in the
window, 256 in the state, and 113 of scratch (a fresh register, the helper or an operand
row, and 49 for the adder).

## Tried, and not used

Measured on earlier versions of this circuit.

- **A scratch register for every operand row, the wide adder throughout, and inner1 computed
  a third time:** 1,312 × 4,495 in 16.0 million operations. This was the first version that
  passed the verifier at full strength.
- **Writing an operand row into a register that takes part in the row's own carries.** The
  carry bit of position k then depends on bit k − 1 of the same register, and the phase
  corrections chain along the word: depth 10,596.
- **The narrow adder in every pass.** The same 1,249 qubits, since the other passes are not
  at the peak, in 19.1 million operations.

## Not done

- Holding every chaining value to the end, as the baseline does: ten passes and no measured
  states. By my count it needs about 480 qubits more at the same depth. Not built.

- A round in fewer than 7 reactions. A sum has a product of two late bits and an early one
  under a 32-bit carry, which is 2 levels and 5.
- Classical arithmetic for the first round of the coinbase block, whose state is classical:
  about 6 reactions at each end.
- An adder in three parts would save about 16 more qubits and does not fit the operation
  limit as the circuit stands.

## Rebuild and verify

`build.py` imports the row arithmetic of `../lean-lookahead-rounds/build.py` and the
hashlib check of `../bitcoin-mining-baseline/build.py`. It checks the circuit twice: once
as written, and once without its resets, since a reset would hide scratch that was not
cleared.

```bash
uv run --project ../../sha256_verifier python build.py
```

```bash
uv run --project ../../sha256_verifier sha-verify pack circuit.kmb --rm
```

```bash
uv run --project ../../sha256_verifier sha-verify run circuit.kmb.zst --problem bitcoin-mining-v1
```
