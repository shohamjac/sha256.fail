# Balanced lookahead rounds, Brent–Kung

A variant of [`../balanced-lookahead-rounds`](../balanced-lookahead-rounds): the same
generator with other carry trees. That directory's README says how the circuit works.

| | This | Balanced lookahead rounds |
|---|---:|---:|
| Qubits | 1,060 | 1,113 |
| Toffolis | 77,304 | 84,150 |
| Reaction depth | 905 | 728 |

The difference: Brent–Kung trees for the sums of a round as well.

A Brent–Kung tree has 104 ANDs against a Sklansky tree's 158, each in a qubit of its own, so this variant
has 53 fewer qubits and 6,846 fewer Toffolis. Its trees have AND-depth 9, not 5, and the depth is 905.

Like the circuit it comes from, it is below 1,000 in reaction depth and below 100,000 in
Toffolis, and is not on the front of either track.

## Rebuild and verify

`build.py` is the generator of `../balanced-lookahead-rounds` with other values for the
constants that choose the trees. It checks the circuit against hashlib twice, once as written
and once without its resets.

```bash
uv run --project ../../sha256_verifier python build.py
```

```bash
uv run --project ../../sha256_verifier sha-verify run circuit.kmb
```
