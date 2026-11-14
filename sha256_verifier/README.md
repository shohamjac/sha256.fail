# sha-verifier

The backend of sha256.fail: checks that a Kickmix circuit computes a hash function and
measures its cost. It knows nothing about leaderboards or the website.

Currently implemented:

- `sha-verify selftest` — runs a 4-bit adder on every input and a set of deliberately broken
  circuits (wrong output, changed input, dirty scratch, missing phase fixup, stray global
  phase), each of which must be detected.
- `sha-verify version` — verifier, Kickmix and platform versions.

- The problem `sha256-compress-v1`: its registers, bit order, reference function, allowed
  instructions and directed tests. The contract is [docs/sha256-compress-v1.md](docs/sha256-compress-v1.md).

Not yet implemented: checking a circuit against a problem (`sha-verify run`), random
sampling, and receipts. That is milestone M2 in `../PLAN.md`.

## Modules

| Module | What |
|---|---|
| `problems.py` | Registry of benchmark problems. Adding a hash function is one entry here. |
| `sha2.py` | Reference SHA-2 compression, vectorized over inputs. Circuit generators must not import it. |
| `bits.py` | Conversion between words and register bit arrays |
| `selftest.py` | Simulator and fault-detection self-test |
| `environment.py` | Kickmix version and binary hash, for receipts |

## Simulator

Kickmix 1.0.0 from PyPI, pinned in `pyproject.toml` with wheel hashes in `uv.lock`. It
corresponds to the signed tag `v1.0.0-kickmix` (commit `e8e4971bf44a`) in
`quantumlib/Qualtran`.

## Develop

```bash
uv sync
uv run pytest
```
