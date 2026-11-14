# sha-verifier

The backend of sha256.fail: checks that a Kickmix circuit computes a hash function and
measures its cost. It knows nothing about leaderboards or the website.

Currently implemented:

- `sha-verify selftest` — runs a 4-bit adder on every input and a set of deliberately broken
  circuits (wrong output, changed input, dirty scratch, missing phase fixup, stray global
  phase), each of which must be detected.
- `sha-verify version` — verifier, Kickmix and platform versions.

The SHA-256 problem definition, sampling, and receipts come next (milestones M1–M2 in
`../PLAN.md`).

## Simulator

Kickmix 1.0.0 from PyPI, pinned in `pyproject.toml` with wheel hashes in `uv.lock`. It
corresponds to the signed tag `v1.0.0-kickmix` (commit `e8e4971bf44a`) in
`quantumlib/Qualtran`.

## Develop

```bash
uv sync
uv run pytest
```
