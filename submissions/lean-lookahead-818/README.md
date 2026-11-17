# Lean lookahead rounds, 818 qubits

A circuit for the reaction-depth track, made to sit on its front between
[`../zero-scratch`](../zero-scratch) and [`../lean-lookahead-rounds`](../lean-lookahead-rounds):
818 qubits at reaction depth 667, with 2,208,566 Toffolis.

| Entry | Qubits | Reaction depth |
|---|---:|---:|
| Zero scratch | 768 | 5,391 |
| In-place rounds, 775 qubits | 775 | 2,074 |
| In-place rounds, 782 qubits | 782 | 1,227 |
| In-place rounds, 786 qubits | 786 | 926 |
| **Lean lookahead rounds, 818 qubits** (this) | 818 | 667 |
| Lean lookahead rounds | 826 | 581 |

The entries between the first and the last come from one generator with different settings.
None has both fewer qubits and less depth than another.

## How it works

It reuses the generator of `../lean-lookahead-rounds`: values kept as rows that are never
stored, a prefix network for the carries, and an in-place adder that erases its carries
with Draper's identity.

- **The rounds of the lean entry**, unchanged: e' and a' in fresh registers from sums whose
  rows are never stored, d and h cleared by subtracting a recomputation in place, the last
  two schedule words never formed.
- **An adder in four parts.** The lean adder takes the word in two halves and holds a
  product of eight propagates in one qubit: 26 scratch qubits. Here the word is taken in
  parts of eight bits, with the carry into each part kept in a qubit of its own until the
  end. Eight for the part, three kept carries and seven for the tree: 18 scratch qubits.

The carry into the top part now passes through three kept carries, one after another, so
an addition is deeper: reaction depth 667 against 581.

## Rebuild and verify

`build.py` imports `../lean-lookahead-rounds/build.py` and, through it, the constants and
the hashlib check of `../example/build.py`. It checks the circuit twice: once as written,
and once without its resets, since a reset would hide scratch that was not cleared.

```bash
uv run --project ../../sha256_verifier python build.py
```

```bash
uv run --project ../../sha256_verifier sha-verify pack circuit.kmb --rm
```

```bash
uv run --project ../../sha256_verifier sha-verify run circuit.kmb.zst
```
