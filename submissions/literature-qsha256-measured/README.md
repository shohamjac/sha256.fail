# qSHA256, measurement-based (literature reconstruction)

A reconstruction of the lowest-cost garbage-free SHA-256 circuit of the
[qSHA256](https://github.com/icedmoca/qSHA256) project by icedmoca (Apache-2.0), rebuilt as a
Kickmix circuit for the problem `sha256-compress-v1` and verified like any other submission.

| | This | qSHA256, Toffoli-only | Baseline |
|---|---:|---:|---:|
| Qubits (Q) | 1,375 | 1,313 | 831 |
| Toffolis per shot (C) | 45,144 | 90,288 | 27,088 |
| Score (Q × C) | 62,073,000 | 118,548,144 | 22,510,128 |

This is the better of qSHA256's two configurations by score, and the one the site shows for
that project. The other is in `../literature-qsha256`. Both are dominated by the baseline.

## What was reconstructed

qSHA256's configuration `gidney/load/rolling/serial/uncomp`, at commit `741fe86`
(version 2.3.0). It has the architecture of the Toffoli-only circuit, with every Toffoli
replaced by a temporary AND (Gidney, [arXiv:1709.06648](https://arxiv.org/abs/1709.06648)):
the AND is computed into a clean ancilla, and later removed by measuring the ancilla in the
X basis and applying a classically controlled CZ.

- Additions are Gidney's ripple-carry adder: 31 carries in ancillas, one AND each.
- Ch and Maj go through a row of 32 AND ancillas.
- 95 ancillas in all, against 33 for the Toffoli-only circuit: 1,375 qubits.
- The uncomputation replays the forward computation backwards, with each computed AND
  becoming a measured removal and each removal a computed AND.

`build.py` is a re-implementation written from reading that project's source, extending
`../literature-qsha256/build.py`. It does not import or run any of the project's code.

## How faithful it is

- **Checked against the project's published numbers.** Its benchmark table lists this
  configuration at 1,375 qubits, 514,364 gates and a T-count of 180,576, which at its 4 T
  per AND is 45,144 ANDs. This reconstruction has exactly those counts; `build.py` asserts
  it on every run. Unlike the Toffoli-only circuit, nothing changed in this configuration
  after the table was generated, so the submitted circuit is the tabulated one.
- **How it is scored here.** qSHA256 reports this circuit as having zero Toffolis and
  45,144 ANDs. This benchmark counts a computed AND as one Toffoli, which is what it is in
  a Kickmix circuit: a `CCX` onto a clean qubit. The removal by measurement costs nothing
  in either accounting.
- **One adaptation,** the same as for the Toffoli-only circuit: the chaining-state register
  is scratch here, loaded with X gates at the start and cleared at the end.

## Rebuild and verify

```bash
uv run --project ../../sha256_verifier python build.py
```

```bash
uv run --project ../../sha256_verifier sha-verify run circuit.kmb.zst
```
