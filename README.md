# sha256.fail

A public benchmark for quantum circuits that compute SHA-256. Submissions are circuit files;
a verifier built on Google's [Kickmix](https://github.com/quantumlib/Qualtran/tree/main/kickmix)
simulator checks each one on about a million random inputs and reports its qubit count and
Toffoli count. Verified circuits are shown on a qubit–Toffoli Pareto front.

Status: early. The verifier works and the problem contract is frozen; the baseline SHA-256
circuit and the website are not built yet, so nothing has passed verification so far. See [PLAN.md](PLAN.md) for the design and milestones.

## Layout

| Path | What |
|---|---|
| `sha256_verifier/` | Backend: the verifier package and `sha-verify` CLI |
| `sha_front/` | Frontend: Pareto front and leaderboard (not started) |
| `submissions/` | One directory per submitted circuit; `example/` will hold the baseline |
| `results/` | Verification receipts written by the verifier, read by the frontend |

The backend and frontend are separate projects. The only thing they share is the receipt
format in `results/`.

## Run the self-test

Needs [uv](https://docs.astral.sh/uv/).

```bash
cd sha256_verifier
uv sync --locked
uv run sha-verify selftest
```

## Licence

Apache-2.0. Kickmix is Apache-2.0, by the Qualtran developers at Google Quantum AI.
