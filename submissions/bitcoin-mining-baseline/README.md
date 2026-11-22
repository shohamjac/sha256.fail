# Bitcoin mining baseline

A plain, readable phase oracle for the problem `bitcoin-mining-v1`: it flips the phase when
the block hash, with the mask XORed in, is below the target. It is the starting point of
that problem's leaderboard. The contract is
[bitcoin-mining-v1.md](../../sha256_verifier/docs/bitcoin-mining-v1.md).

| | |
|---|---:|
| Qubits (Q) | 2,000 |
| Toffolis per shot (C) | 262,158 |
| Score (Q × C) | 524,316,000 |
| Reaction depth (D) | 108,224 |
| Operations | 3,526,903 |

Verified at full strength before it was committed: 2,848 shots on 16 real blocks and
1,048,576 random shots, all correct. The official receipt is recorded in
`../../results/bitcoin-mining-v1/` when this directory is merged.

## Files

| File | What |
|---|---|
| `circuit.kmb.zst` | The circuit that is verified, zstd-compressed |
| `meta.json` | Name, authors, kind, problem and description, carried into the receipt |
| `build.py` | How the circuit was generated. Never run by the verifier. |

## How it works

- **Five compressions, each as in the compression baseline.** A compression is built the
  way [`../example`](../example) builds one: the state is updated in place over 64 rounds,
  the message schedule is expanded in place over the block, and the additions are Kickmix's
  ripple-carry adder, which clears its carries by measurement.
- **One state register per compression, one block register for all.** The five 256-qubit
  states are `inner1`, `root`, `mid`, `inner2` and the hash. A block is XORed into the
  shared 512-qubit block register before its compression. After the compression its
  schedule is rewound and the block is XORed out, which leaves the register at zero for the
  next one.
- **Classical inputs are copied into qubits.** A classical word is XORed into the block or
  state register with `X` gates under classical conditions, and is then handled like a
  quantum word.
- **Mask, compare, phase.** The mask is XORed into `H_5`, `H_6` and `H_7`. The target from
  bit 160 up is worked out from `bits` with classical operations, which cost nothing. A
  comparison sets one qubit, a `Z` on it is the phase, and the comparison is undone.
- **Then everything backwards.** Every step records its inverse as it is emitted, and the
  list is replayed in reverse. The last compression's block is never rewound on the way
  forward, since the way back would start by expanding it again.

Where the qubits go: 80 in the search register, 1,280 in the five states, 512 in the block
register, 32 in a temporary that holds Sigma, Ch or Maj while it is added, and 96 for the
comparison's result and work qubits, which the adders' 31 carries share.

Where the Toffolis go:

| Part | Count |
|---|---:|
| Rounds: 5 compressions forward and 5 backward, 64 rounds at 280 each | 179,200 |
| Schedule: 432 steps forward (5 expansions and 4 rewinds of 48) and 432 backward, at 93 each | 80,352 |
| The 8 final additions of each compression, forward and backward | 2,416 |
| The comparison, done twice | 190 |
| Total | 262,158 |

No Toffoli is under a classical condition, so the count executed per shot is the count in
the circuit.

## Known slack

This is a baseline, not an optimized circuit. Some of what it leaves on the table:

- **Classical words are treated as quantum.** Most of the coinbase's last block and of the
  header is classical, and so are the paddings. Their part of the message schedule, and the
  first rounds of the header's first block, could be computed classically for free.
- **The whole hash is computed.** The answer depends only on `H_5`, `H_6` and `H_7` of the
  last compression, so its last rounds do more than is needed.
- **Everything is computed twice.** The backward pass costs as much as the forward one.
- **Each compression keeps its own state.** Five states are held to the end.

## Rebuild and verify

```bash
uv run --project ../../sha256_verifier python build.py
```

```bash
uv run --project ../../sha256_verifier sha-verify run circuit.kmb.zst --problem bitcoin-mining-v1
```

`build.py` checks the circuit against `hashlib` and does not import the verifier, so the
circuit and the verifier's reference function are two independent implementations.
