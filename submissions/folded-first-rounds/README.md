# Folded first rounds

The baseline (`../example`) with its first four rounds simplified by constant folding.

| | This | Baseline |
|---|---:|---:|
| Qubits (Q) | 831 | 831 |
| Toffolis per shot (C) | 26,716 | 27,088 |
| Score (Q × C) | 22,200,996 | 22,510,128 |

Same qubits, 372 fewer Toffolis: it dominates the baseline.

## The idea

SHA-256 starts from a fixed initial hash value, so in the first rounds part of the state is
a known constant, and the circuit does not need to compute with it.

| Round | What is constant | Saving |
|---|---|---:|
| 0 | all of a..h | 218 |
| 1 | f, g, b, c, and h | 94 |
| 2 | g, and h | 30 |
| 3 | h | 30 |

- **Round 0.** T1 is a constant plus W_0 and T2 is a constant. The two registers the round
  changes are loaded with their constant parts and W_0 is added to each: two additions
  instead of seven additions and two rows of ANDs.
- **Round 1.** With f, g constant, each bit of Ch(e, f, g) is a constant, e, or not-e; with
  b, c constant, each bit of Maj(a, b, c) is a constant or a. CNOTs and X gates, no ANDs.
- **Rounds 1 to 3.** The register serving as h still holds a constant, so the round
  constant K_t is added into it at build time rather than by an adder.

From round 4 on, and in the message schedule, nothing is known in advance and the circuit is
the baseline unchanged.

## Rebuild and verify

```bash
uv run --project ../../sha256_verifier python build.py
```

```bash
uv run --project ../../sha256_verifier sha-verify run circuit.kmb
```
