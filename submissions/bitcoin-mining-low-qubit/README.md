# Bitcoin mining on 1,072 qubits

A phase oracle for the problem `bitcoin-mining-v1` on 1,072 qubits, against the baseline's
2,000. The contract is
[bitcoin-mining-v1.md](../../sha256_verifier/docs/bitcoin-mining-v1.md).

| | This | [Baseline](../bitcoin-mining-baseline) |
|---|---:|---:|
| Qubits (Q) | 1,072 | 2,000 |
| Toffolis per shot (C) | 522,269 | 262,158 |
| Score (Q × C) | 559,872,368 | 524,316,000 |
| Reaction depth (D) | 130,657 | 108,224 |
| Operations | 5,688,103 | 3,526,903 |

It is built for the fewest qubits, not for the score. Verified at full strength: 2,848
shots on 16 real blocks and 1,048,576 random shots, all correct. The official receipt is
recorded in `../../results/bitcoin-mining-v1/` when this directory is merged.

## The idea: measure a result away, pay for it later

The oracle is a chain of five compressions:

```
inner1 → root → mid → inner2 → hash
```

The baseline keeps all five results until the phase is applied and then runs everything
backwards. Each result is 256 qubits.

Here a value is measured in the X basis as soon as nothing ahead needs it. Its qubits are
free at once. What the measurement leaves is a phase `(−1)^(m·v)`, with `m` the measured
bits and `v` the value. The phase is removed later: the value is computed again, and a `Z`
is applied to each of its qubits whose measured bit was one. Computing a value again costs
Toffolis and no extra qubits, so the circuit never holds more than one compression and
that compression's inputs.

Written with P for "compute", U for "uncompute by running backwards", G for "measure away"
and Z for "remove the phase of an earlier G", the order of work is:

```
forward   P1 P2 G1 P3 G2 P4 G3 P5 [phase] U5 G4
pass 1    P1 Z1 P2 Z2 G1 P3 Z3 G2 P4 Z4 U4 G3
pass 2    P1 Z1 P2 Z2 G1 P3 Z3 U3 G2
pass 3    P1 Z1 P2 Z2 U2 U1
```

Each pass exists to uncompute one more result properly, which needs the result before it
to be present. Holding that earlier result while the later ones are recomputed would not
fit, so it is measured away and the chain is started again from the search register.

## Where the 1,072 qubits go

The largest compression is the header's second block. It is the only one whose starting
state is not classical, and the starting state is added to the result at the end, so it
has to be kept.

| Qubits | What |
|---:|---|
| 48 | `extranonce`, idle |
| 256 | mid, kept for the addition that ends the compression |
| 256 | the state being worked on |
| 512 | the message schedule, which runs in place over the nonce and the root's last word |
| **1,072** | |

From round 33 on, all 16 words of the schedule depend on the search register, and from
round 30 the circuit has every qubit in use. The other four compressions peak at 912, 912,
944 and 912 qubits, so this one block sets the count.

I found no way under 1,072 with a schedule computed by its recurrence. Three things would
each have to give: the 16 live schedule words, the state, or the kept copy of mid. Dropping
the copy and computing mid again at the end needs 1,104 qubits, because the block being
recomputed needs its own 768 while the 256 of the unfinished result wait. This is the floor
of this layout, not a proven lower bound for the problem.

## How each compression is built

- **The four with room** (coinbase block, root, header's first block, hash) use the
  baseline's arithmetic: Kickmix's adder with measured carries, and a 32-qubit temporary for
  Sigma, Ch and Maj values. The schedule runs in place over the block's quantum words, so
  the 256 qubits of an input digest are also 8 of the 16 schedule words.
- **Padding words are constants, not qubits.** A constant word of a block gets qubits only
  when the schedule overwrites it. Until then it is added as a constant, together with the
  round constant.
- **The header's second block, rounds 0 to 29.** Its padding words are still unallocated,
  which leaves at least 63 qubits: enough for the baseline's arithmetic.
- **The header's second block, rounds 30 to 63.** No qubit is free. These rounds are the
  pieces of [`../zero-scratch`](../zero-scratch): additions that keep their carries in the
  wires of the number being added, Sigma functions made in place by CNOTs, Ch and Maj
  computed onto one of their own inputs, and round constants added as signed binary digits.
  They use no measurement, so running them backwards is the same gates in reverse order.
- **Expanded schedules are measured away, not rewound,** wherever the block's quantum words
  would be measured away next anyway. The phase is removed the next time the same schedule
  is expanded. For the coinbase block the schedule runs on a copy of the extranonce, 48
  qubits that are free there, so that this works without touching the search register.
- **The last compression is computed and uncomputed around the comparison,** as in the
  baseline, with its schedule left expanded in between.

## Where the Toffolis go

| Part | Count |
|---|---:|
| Coinbase block: computed 4 times at 22,624, uncomputed once at 27,088 | 117,584 |
| Root: computed 4 times and uncomputed once, 21,969 each | 109,845 |
| Header's first block: computed 3 times and uncomputed once, 22,624 each | 90,496 |
| Header's second block: computed once with its schedule rewound (57,824), then computed and uncomputed (102,392) | 160,216 |
| Hash: computed and uncomputed, 21,969 each | 43,938 |
| The comparison, done twice | 190 |
| Total | 522,269 |

No Toffoli is under a classical condition, so the count executed per shot is the count in
the circuit.

## Known slack

- **Two more qubits.** In rounds 30 to 63 of the header's second block a round constant
  costs 558 Toffolis on average, and there are 102 such additions: 56,874 Toffolis. Gidney's
  constant adder ([arXiv:2507.23079](https://arxiv.org/abs/2507.23079)) needs 2 clean qubits
  and about 96 Toffolis. At 1,074 qubits that should save about 47,000 Toffolis. Not built.
- **Classical inputs are still treated as quantum,** except for the padding. The schedule
  words and first rounds that depend only on `tail`, `version`, `prev_hash`, `time` and
  `bits` could be computed classically.
- **The whole hash is computed.** Only `H_5`, `H_6` and `H_7` are compared.

## Files

| File | What |
|---|---|
| `circuit.kmb.zst` | The circuit that is verified, zstd-compressed |
| `meta.json` | Name, authors, kind, problem and description, carried into the receipt |
| `build.py` | How the circuit was generated. Never run by the verifier. |

## Rebuild and verify

```bash
uv run --project ../../sha256_verifier python build.py
```

```bash
uv run --project ../../sha256_verifier sha-verify run --problem bitcoin-mining-v1 circuit.kmb.zst
```

`build.py` imports the generators of `../bitcoin-mining-baseline` and `../zero-scratch`,
and checks the circuit against `hashlib` on 1,024 made-up blocks before writing it.
