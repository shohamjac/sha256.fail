# Balanced lookahead rounds, compact

[`../balanced-lookahead-rounds`](../balanced-lookahead-rounds) with its scratch cut down:
still below 1,000 in reaction depth and below 100,000 Toffolis, on 197 fewer qubits.

| | This | Balanced lookahead rounds | its Brent–Kung variant |
|---|---:|---:|---:|
| Qubits | 916 | 1,113 | 1,060 |
| Toffolis | 97,249 | 84,150 | 77,304 |
| Reaction depth | 905 | 728 | 905 |

The room under the two limits is spent on qubits here. It is not on the front of either
track: the circuits made for one track use fewer qubits. The Toffoli count is exact, since
no Toffoli is under a classical condition.

## What changed

The method is the one of Balanced lookahead rounds: every AND goes into a qubit of its own
and is measured away, every value in between is an XOR of register qubits and AND qubits,
new registers are formed from one carry-save sum and one carry tree, and dropped registers
are measured in the X basis with the phase fixed on the bits of a second sum.

- **The carries become the register.** Bit k of a sum is its propagate XOR the carry into
  it. When a sum forms a register, its carries are built in place in 31 qubits, and each of
  those qubits then takes the propagate of its bit and is the bit. The register costs no
  qubits beyond its carries, and the carries are never uncomputed. Before, the sum was
  copied into 32 more qubits and the whole tree measured away.
- **Measure first.** A dropped register is measured before the sum that fixes its phase is
  computed. Its 32 qubits are free during that sum, and the measured bits wait.
- **Carries merged in place, where it pays.** In a sum that only fixes a phase, a merge of
  the carry tree can write into the qubit it updates, with a Toffoli that a Toffoli undoes.
  Each such merge saves a qubit and costs a Toffoli. All merges are done so in the rounds,
  18 a tree in the schedule, and all in the clearing step of the rewind.
- **Shared rows without their ANDs.** The sums for e' and h share two rows, made by three
  carry-save steps from d, K, W, Σ1 and Ch. Kept as they are, they need 124 qubits. Here
  the XOR row is written into a register and only the last carry row stays, 63 qubits. The
  other ANDs are measured away, which is free, and made again when the rows are taken
  apart. The first carry row is made four times in all, so that no more than three of the
  four rows are ever held at once.
- **Brent–Kung trees**, which have the fewest nodes, except in the clearing step of the
  rewind, where a Sklansky tree keeps the chain short.

## Where the depth and the Toffolis go

A round has AND-depth 11: Ch, two carry-save steps, and a Brent–Kung tree. After 64 rounds
that is 701. The rewind is a chain of 24 steps of about 8 reactions, which gives 905.

Toffolis: 986 a round, 279 of them for the shared rows; 15,264 for the schedule, 20,640 for
its rewind and 828 for the final addition.

Qubits: 768 for the registers and 148 at the peak, in a round: the two shared rows, one
more carry row, the carries of the tree and the propagates of its nodes.

## Other settings

The trees of the sums that fix a phase are set by constants at the top of `build.py`.
Measured:

| Change | Qubits | Depth | Toffolis |
|---|---:|---:|---:|
| As submitted | 916 | 905 | 97,249 |
| Brent–Kung, 18 merges in place, for the clearing step of the rewind | 916 | 975 | 91,873 |
| No merges in place in the schedule | 934 | 905 | 96,385 |
| 40 merges in place in the rounds, not all | 927 | 905 | 95,869 |

## Rebuild and verify

`build.py` imports the constants and the hashlib check from `../example/build.py`. It checks
the circuit twice: once as written, and once without its resets, since a reset would hide
scratch that was not cleared.

```bash
uv run --project ../../sha256_verifier python build.py
```

```bash
uv run --project ../../sha256_verifier sha-verify run circuit.kmb
```
