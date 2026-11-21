# sha-verifier

The backend of sha256.fail: checks that a Kickmix circuit computes a hash function and
measures its cost. It knows nothing about leaderboards or the website; its only output is
a receipt.

## Verify a circuit

```bash
uv sync --locked
uv run sha-verify run circuit.kmb
```

The circuit file is a Kickmix `.kmb` or `.kmx`, either as is or zstd-compressed
(`circuit.kmb.zst`). `sha-verify pack circuit.kmb` compresses one; submissions over 1 MiB
must be committed that way. A compressed file must be a single zstd frame, and it is
decompressed only up to the same size limit as an uncompressed one. The receipt's
`file_sha256` is the hash of the decompressed file, so it does not depend on compression.

This checks the circuit against `sha256-compress-v1` (the contract is
[docs/sha256-compress-v1.md](docs/sha256-compress-v1.md)), prints a receipt as JSON, and
exits 0 if the circuit passed and 1 if it did not. A full run is 1,179 directed tests and
2^20 random ones; on a 300,000-gate circuit that takes about 40 s on one core.

| Option | Meaning |
|---|---|
| `--shots N` | Fewer random tests, for development. The receipt is marked `full_strength: false`. |
| `--salt S` | Salt mixed into the seed that picks the random tests. Default: empty. |
| `--random-salt` | Draw a fresh salt and record it. Use this when others must trust the result. |
| `--workers N` | Worker processes. Does not change the result. |
| `--meta FILE` | JSON object with submission metadata, carried in the receipt unchanged. |
| `--results-dir DIR` | Also write the receipt to `DIR/<problem>/<circuit sha256>.json`. |

Other commands:

- `sha-verify replay RECEIPT CIRCUIT` re-runs a verification with the salt and shot count in
  a receipt and checks that the result is identical.
- `sha-verify collect DIR` gathers every receipt under `DIR` into `DIR/index.json`, which is
  what the frontend reads.
- `sha-verify check-submission DIR` checks a submission directory's layout and `meta.json`.
- `sha-verify record SUBMISSIONS RESULTS` verifies every submission that has no up-to-date
  receipt and writes the receipts. CI runs this on `main`.
- `sha-verify pr-check` and `sha-verify pr-verify` are what CI runs on a pull request; they
  produce the comment the bot posts.
- `sha-verify selftest` checks the simulator stack itself.

## What is checked

1. **Load.** The file is parsed by Kickmix, written back out as text, and that text is read
   again by an independent parser (`kmx.py`). The two must agree on every count, and only
   a circuit rebuilt from the text is simulated.
2. **Structure.** Exactly the problem's registers, of the right sizes, made of distinct
   qubits; only allowed instructions; within the size limits.
3. **Directed tests**, then **random tests.** Every shot must end with the right output,
   inputs unchanged, scratch at zero and phase not flipped.
4. **Accounting.** The executed Toffoli count must be possible for the circuit's static count.

The first failure stops the run. The receipt names the stage, the check, and the failing
input, so a failure can be reproduced.

## Receipts

Described by [schema/receipt.schema.json](schema/receipt.schema.json). Everything except the
`run` section depends only on the circuit, the problem, the salt and the number of random
shots: re-running with the same four gives the same receipt, on any machine and with any
number of workers. The random tests are derived from
`SHA-256(problem, circuit hash, salt)`; see `sampling.py`.

## Limits

A submission may be at most 512 MiB, 20,000,000 operations, 65,536 qubits and 1,048,576
classical bits.

## Running on untrusted files

The verifier never executes submitted code, only parses circuit files. Parsing is done by
Kickmix's C++ loader, so run the verifier where a crash or a large allocation costs nothing
but the run: a throwaway CI job with no secrets, as the workflow here does.

## Modules

| Module | What |
|---|---|
| `verify.py` | `verify(bytes, problem, salt, ...) -> receipt`: the whole verifier as one function |
| `circuits.py` | Loading a file, the cross-check against Kickmix, structural checks, limits |
| `kmx.py` | Independent parser for Kickmix circuit text |
| `sampling.py` | Seed derivation and random inputs |
| `simulate.py` | Batched simulation and the per-shot checks |
| `submission.py` | Rules for submission directories and pull requests, recording receipts, comment text |
| `problems.py` | Registry of benchmark problems. Adding a hash function is one entry here. |
| `sha2.py` | Reference SHA-2 compression. Circuit generators must not import it. |
| `bits.py` | Conversion between words and register bit arrays |
| `selftest.py`, `environment.py` | Simulator self-test; Kickmix version and binary hash |

## Simulator

Kickmix 1.0.0 from PyPI, pinned in `pyproject.toml` with wheel hashes in `uv.lock`. It
corresponds to the signed tag `v1.0.0-kickmix` (commit `e8e4971bf44a`) in
`quantumlib/Qualtran`.

## Develop

```bash
uv sync
uv run pytest
```

The tests include a small 4-bit adder problem (`tests/toy.py`) with about thirty broken
circuits that must each be rejected at a specific stage for a specific reason, and the
baseline SHA-256 circuit from `../submissions/example`, which must pass and whose mutants
must fail.
