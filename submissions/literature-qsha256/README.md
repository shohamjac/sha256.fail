# qSHA256, Toffoli-only (literature reconstruction)

A reconstruction of the garbage-free SHA-256 compression circuit of the
[qSHA256](https://github.com/icedmoca/qSHA256) project by icedmoca (Apache-2.0), rebuilt as a
Kickmix circuit for the problem `sha256-compress-v1` and verified like any other submission.

| | This | Baseline |
|---|---:|---:|
| Qubits (Q) | 1,313 | 831 |
| Toffolis per shot (C) | 90,288 | 27,088 |
| Score (Q × C) | 118,548,144 | 22,510,128 |

It is dominated by the baseline. The comparison is not like for like: this circuit uses only
X, CNOT and Toffoli gates, with no measurement, while the baseline clears carries and ANDs
by measurement.

qSHA256 also has a measurement-based configuration, rebuilt in
`../literature-qsha256-measured`: 1,375 qubits and 45,144 Toffolis. That one has the better
score, so it is the one the site shows for this project. This circuit is verified and has a
receipt, but is not on the chart or the leaderboard.

## What was reconstructed

qSHA256's default architecture with uncomputation enabled
(`cdkm/load/rolling/serial/uncomp`), at commit `741fe86` (version 2.3.0):

- Chaining state, message, working variables and digest in separate registers, plus 33
  ancillas: 1,313 qubits.
- Rounds update two registers in place and relabel the rest; the message schedule rolls in
  place over the message.
- Every addition is the Cuccaro ripple-carry adder. Ch and Maj are computed into a temporary
  with Toffolis and erased by repeating the same gates.
- The digest is formed in its own register, then the whole forward computation is replayed
  backwards.

`build.py` is a re-implementation written from reading that project's source. It does not
import or run any of it.

## How faithful it is

- **Checked against the project's published numbers.** Its benchmark table lists this
  configuration at 1,313 qubits, 92,672 Toffolis and 399,044 gates. Built with the adder
  that table was generated with, this reconstruction gives exactly those three numbers;
  `build.py` asserts it on every run.
- **The submitted circuit uses the project's current adder.** Version 2.3.0 changed the
  adder from 2n to 2(n−1) Toffolis per addition, after the table was generated. With 1,192
  additions that is 2,384 fewer: 90,288. That figure is derived here, not quoted from the
  project.
- **One adaptation.** In this problem the chaining state is fixed, so its register is
  scratch: it is set to the initial hash value with X gates at the start and cleared with
  the same gates at the end. qSHA256 leaves that register holding its input. This adds X
  gates only.

## Rebuild and verify

```bash
uv run --project ../../sha256_verifier python build.py
```

```bash
uv run --project ../../sha256_verifier sha-verify run circuit.kmb
```
