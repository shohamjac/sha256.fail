# Lookahead rounds, everything computed again

A phase oracle for the problem `bitcoin-mining-v1`, built for the reaction-depth track. The
contract is [bitcoin-mining-v1.md](../../sha256_verifier/docs/bitcoin-mining-v1.md). It
starts from [Lookahead rounds, states measured away](../bitcoin-mining-low-depth) and holds
less.

| | This | [States measured away](../bitcoin-mining-low-depth) | [Baseline](../bitcoin-mining-baseline) |
|---|---:|---:|---:|
| Qubits (Q) | 1,130 | 1,249 | 2,000 |
| Reaction depth (D) | 4,331 | 4,435 | 108,224 |
| Score on the depth track (Q × D) | 4,894,030 | 5,539,315 | 216,448,000 |
| Toffolis | 6,516,029 | 7,575,806 | 262,158 |
| Operations | 16,113,536 | 17,484,731 | 3,526,903 |

The depth-track score is 11.6% below the circuit it starts from and 44 times below the
baseline. Toffolis are not scored on this track and the circuit spends them freely.

Verified at full strength before it was written up: 2,848 shots on 16 real blocks and
1,048,576 random shots with a random salt, all correct.

## What it keeps

The sums are those of [Lean lookahead rounds](../lean-lookahead-rounds): carry-save rows and
an adder of AND-depth 5, which give 7 reactions per round on the way forward and 7 per round
on the way back. A value that is no longer needed is measured away in the X basis, and the
phase this leaves is cancelled with Z gates when the same value is computed again. A value
computed again starts from the search register, so it is no deeper than the first time:
computing again costs operations and no depth. The limit that binds is the problem's
20,000,000 operations.

## What is new

- **Forward rounds clear nothing.** Before, a round cleared the two registers it drops by
  subtracting a recomputation, as the lean rounds do. Here the registers a round is done
  with (a helper, h and d) are measured away. The round that undoes it forms those values
  anyway, and their phase is corrected there. A forward round is about 7,000 operations,
  against 17,000.
- **Compute more often, hold less.** Undoing a compression needs the output of the one
  before. That output is now computed again from the search register each time it is
  needed, with nothing else held, where the earlier circuit kept two chaining values next
  to the compression it was working on. There are 18 passes of 64 rounds, not 12, but 13 of
  them are forward passes.
- **The header's second block sets the count, by itself.** It needs its schedule window,
  the midstate for the feed-forward and its own state. The window is now the schedule in
  place over the nonce and over the last word of the merkle root, with no copies. Since it
  holds the nonce it cannot be measured away: on the way forward it is rewound, and on the
  way back the block is computed and undone in one go.
- **One register beyond the state, not two.** h is measured away before e' is formed, since
  the helper has it added in already. a' is formed with e' − d as the adder's operand,
  written into the register of d. Undoing a round follows the same shape: it forms
  a' − Σ0 − Maj, clears a' against it, and turns it into d in place; then the same for e'
  and h.
- **The lean adder where the count is set.** In the three passes over the header's second
  block, and in one pass that runs next to a held value, additions use the adder of the
  lean rounds itself: 26 scratch qubits and 1,860 operations. Everywhere else they use the
  adder that keeps its propagate products in qubits: 80 scratch qubits and 730 operations.
- **The last compression keeps the roomier rounds.** Right after the phase flip nothing
  hides AND-depth, and in the one-register way of undoing a round it grows by 11 per round.
  The last compression is far from the qubit peak, so its rounds keep a second register.

## Where the depth goes

| Part | Depth after it |
|---|---:|
| coinbase block, merkle root, header's first block → midstate | 1,292 |
| header, second block | 1,730 |
| second hash → the three compared words (63 rounds) | 2,161 |
| comparison and phase | 2,165 |
| undo the block hash | 2,620 |
| compute the midstate again | 2,620 |
| header's second block, computed and undone | 3,073 |
| compute the midstate a third time | 3,073 |
| undo the header's first block | 3,515 |
| compute inner1 again, undo the merkle root | 3,875 |
| undo the coinbase block | 4,331 |

The 310 rounds on the longest chain, at 7 forward and 7 back, are 4,340.

Qubits at the peak, in the header's second block: 48 of the search register that it does
not use, 512 in the window (the nonce and the root's last word among them), 256 in the
midstate, 256 in the state, one fresh register of 32, and 26 for the adder.

## Tried, and not used

Measured on earlier versions of this circuit.

- **Two registers beyond the state in every round:** 1,162 × 4,440.
- **One register beyond the state in the last compression too:** 1,130 × 4,579. See the
  last point above.

## Not done

- A round in fewer than 7 reactions. The carry row of the carry-save step has a product of
  two late bits and an early one, which puts the adder's propagate bits 2 levels after the
  late input, and the 32-bit carry takes 5 more.
- An adder with less scratch than 26 in the header's second block. A split into more parts
  might save about 6 qubits.
- Below 1,072 qubits before scratch: the header's second block needs the midstate and its
  own state at once, for the feed-forward.

## Rebuild and verify

`build.py` imports the row arithmetic and the adder of `../lean-lookahead-rounds/build.py`
and the hashlib check of `../bitcoin-mining-baseline/build.py`. It checks the circuit twice:
once as written, and once without its resets, since a reset would hide scratch that was not
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
