# Balanced lookahead rounds, Sklansky

A variant of [`../balanced-lookahead-rounds`](../balanced-lookahead-rounds): the same
generator with other carry trees. That directory's README says how the circuit works.

| | This | Balanced lookahead rounds |
|---|---:|---:|
| Qubits | 1,113 | 1,113 |
| Toffolis | 98,202 | 84,150 |
| Reaction depth | 717 | 728 |

The difference: Sklansky trees everywhere but the final addition.

A Sklansky tree has AND-depth 5 against a Brent–Kung tree's 9, and 158 ANDs against 104. Using it for every
sum of the rounds, the schedule and the rewind takes 11 off the depth and adds 14,052 Toffolis. The qubit
count is the same, since the peak is in a round's Sklansky tree either way.

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
