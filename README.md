# sha256.fail

**[shohamjac.github.io/sha256.fail](https://shohamjac.github.io/sha256.fail/)**

A public benchmark for quantum circuits that compute SHA-256. Submissions are circuit files;
a verifier built on Google's [Kickmix](https://github.com/quantumlib/Qualtran/tree/main/kickmix)
simulator checks each one on about a million random inputs and reports its qubit count,
Toffoli count and reaction depth. Circuits are ranked on two tracks, qubits × Toffolis and
qubits × reaction depth, each with its own Pareto front.

Status: early. The verifier works, the problem contract is frozen, and a baseline circuit
passes at full strength: 831 qubits and 27,088 Toffolis. Pull requests that add a circuit are
verified automatically, and the site is rebuilt whenever one is merged.

To submit a circuit, see [submissions/README.md](submissions/README.md). See [PLAN.md](PLAN.md) for the design and milestones.

## Layout

| Path | What |
|---|---|
| `sha256_verifier/` | Backend: the verifier package and `sha-verify` CLI |
| `sha_front/` | Frontend: Pareto front, leaderboard and rules pages |
| `submissions/` | One directory per submitted circuit: `example/` is the baseline, two are variants of it, and `literature-*` are reconstructions of published circuits |
| `results/` | Verification receipts written by the verifier, read by the frontend |

The backend and frontend are separate projects. The only thing they share is the receipt
format in `results/`.

## Verify a circuit

Needs [uv](https://docs.astral.sh/uv/).

```bash
cd sha256_verifier
uv sync --locked
uv run sha-verify run ../submissions/example/circuit.kmb.zst
```

The task a circuit must perform is specified in
[sha256_verifier/docs/sha256-compress-v1.md](sha256_verifier/docs/sha256-compress-v1.md).

## Licence

Apache-2.0. Kickmix is Apache-2.0, by the Qualtran developers at Google Quantum AI.
