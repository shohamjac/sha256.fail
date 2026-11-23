# Bitcoin mining with kept carries, on 16,384 qubits

The circuit of [`../bitcoin-mining-low-toffoli`](../bitcoin-mining-low-toffoli) for the
problem `bitcoin-mining-v1`, built on 16,384 qubits instead of 65,536. It is one point on
that design's line of qubits against Toffolis. The contract is
[bitcoin-mining-v1.md](../../sha256_verifier/docs/bitcoin-mining-v1.md).

| | This | [65,536 qubits](../bitcoin-mining-low-toffoli) | [Baseline](../bitcoin-mining-baseline) |
|---|---:|---:|---:|
| Qubits (Q) | 16,384 | 65,536 | 2,000 |
| Toffolis per shot (C) | 189,744 | 140,592 | 262,158 |
| Toffolis in the circuit | 190,403 | 141,251 | 262,158 |
| Score (Q × C) | 3,108,763,376 | 9,213,828,018 | 524,316,000 |
| Reaction depth (D) | 16,676 | 17,169 | 108,224 |
| Operations | 2,170,650 | 1,907,548 | 3,526,903 |

Verified at full strength with a random salt: 2,848 shots on 16 real blocks and 1,048,576
random shots, all correct. The official receipt is recorded in
`../../results/bitcoin-mining-v1/` when this directory is merged.

## What it is

The oracle computes the hash, flips the phase, and undoes the hash. An addition that leaves
its carries in qubits of their own is undone with CNOTs and measurements, with no Toffoli.
So each spare qubit saves one Toffoli of the way back, and the circuit keeps ANDs until its
qubits run out.

Here 3,167 qubits hold the search register and the registers the five compressions work in,
and the other 13,217 each hold one kept AND:

| | ANDs |
|---|---:|
| Computed on the way forward | 101,985 |
| Of those, kept in qubits | 13,217 |
| Computed again on the way back | 88,418 |
| Toffolis in the circuit | 190,403 |

The way forward is the same at every number of qubits. What it does to need only 101,985
ANDs, and why the count per shot is below the count in the circuit, is in the
[README of the 65,536-qubit entry](../bitcoin-mining-low-toffoli/README.md).

## The line

| Qubits | Toffolis per shot | Entry |
|---:|---:|---|
| 3,167 | 202,961 | [`bitcoin-mining-low-toffoli-3167`](../bitcoin-mining-low-toffoli-3167) |
| 16,384 | 189,744 | this one |
| 32,768 | 173,360 | [`bitcoin-mining-low-toffoli-32768`](../bitcoin-mining-low-toffoli-32768) |
| 65,536 | 140,592 | [`bitcoin-mining-low-toffoli`](../bitcoin-mining-low-toffoli) |

Every qubit taken away costs one Toffoli, and no point on the line has both fewer qubits
and fewer Toffolis than another.

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
