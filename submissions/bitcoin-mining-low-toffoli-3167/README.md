# Bitcoin mining with classical inputs kept classical, on 3,167 qubits

The circuit of [`../bitcoin-mining-low-toffoli`](../bitcoin-mining-low-toffoli) for the
problem `bitcoin-mining-v1`, built on the fewest qubits that design can use. It is the low
end of that design's line of qubits against Toffolis. The contract is
[bitcoin-mining-v1.md](../../sha256_verifier/docs/bitcoin-mining-v1.md).

| | This | [65,536 qubits](../bitcoin-mining-low-toffoli) | [Baseline](../bitcoin-mining-baseline) |
|---|---:|---:|---:|
| Qubits (Q) | 3,167 | 65,536 | 2,000 |
| Toffolis per shot (C) | 202,961 | 140,592 | 262,158 |
| Toffolis in the circuit | 203,620 | 141,251 | 262,158 |
| Score (Q × C) | 642,776,797 | 9,213,828,018 | 524,316,000 |
| Reaction depth (D) | 16,622 | 17,169 | 108,224 |
| Operations | 2,244,227 | 1,907,548 | 3,526,903 |

Verified at full strength with a random salt: 2,848 shots on 16 real blocks and 1,048,576
random shots, all correct. The official receipt is recorded in
`../../results/bitcoin-mining-v1/` when this directory is merged.

## What it is

The 65,536-qubit entry saves Toffolis in two ways. It needs few ANDs to compute the hash,
and it keeps most of them in spare qubits, which makes them free to undo. This entry has
no spare qubit: 3,167 qubits are the search register and the registers the five
compressions work in. No AND is kept, and the way back computes each one again.

| | ANDs |
|---|---:|
| Computed on the way forward | 101,985 |
| Of those, kept in qubits | 0 |
| Computed again on the way back | 101,635 |
| Toffolis in the circuit | 203,620 |

So what is left is the way forward, which is the same at every number of qubits:

- Only the 80 searched bits are qubits. Sums of classical words are worked out on classical
  bits and reach the qubits as one addend, and Ch and Maj with classical arguments need no
  AND.
- The last compression computes only the three compared words, and skips the rounds an
  easy exponent does not need.
- Additions are paired and round constants give units to free carry-ins.

The details are in the
[README of the 65,536-qubit entry](../bitcoin-mining-low-toffoli/README.md).

It uses more qubits than the baseline because no register is rewound: each compression
leaves its last 16 schedule words and its state where they are, and the way back uses
them.

## The line

| Qubits | Toffolis per shot | Entry |
|---:|---:|---|
| 3,167 | 202,961 | this one |
| 16,384 | 189,744 | [`bitcoin-mining-low-toffoli-16384`](../bitcoin-mining-low-toffoli-16384) |
| 32,768 | 173,360 | [`bitcoin-mining-low-toffoli-32768`](../bitcoin-mining-low-toffoli-32768) |
| 65,536 | 140,592 | [`bitcoin-mining-low-toffoli`](../bitcoin-mining-low-toffoli) |

Every qubit added saves one Toffoli, and no point on the line has both fewer qubits and
fewer Toffolis than another.

## Rebuild and verify

```bash
uv run --project ../../sha256_verifier python build.py
```

```bash
uv run --project ../../sha256_verifier sha-verify run circuit.kmb.zst --problem bitcoin-mining-v1
```

`build.py` here is a few lines: it imports the generator in
[`../bitcoin-mining-low-toffoli`](../bitcoin-mining-low-toffoli) and runs it with this
entry's number of qubits, so that directory has to be present. The generator checks the
circuit against `hashlib`.
