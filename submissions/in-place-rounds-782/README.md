# In-place rounds, 782 qubits

A circuit for the reaction-depth track, made to sit on its front between
[`../zero-scratch`](../zero-scratch) and [`../lean-lookahead-rounds`](../lean-lookahead-rounds):
782 qubits at reaction depth 1,227, with 728,048 Toffolis.

| Entry | Qubits | Reaction depth |
|---|---:|---:|
| Zero scratch | 768 | 5,391 |
| In-place rounds, 775 qubits | 775 | 2,074 |
| **In-place rounds, 782 qubits** (this) | 782 | 1,227 |
| In-place rounds, 786 qubits | 786 | 926 |
| Lean lookahead rounds, 818 qubits | 818 | 667 |
| Lean lookahead rounds | 826 | 581 |

The entries between the first and the last come from one generator with different settings.
None has both fewer qubits and less depth than another.

## How it works

It reuses the generator of `../lean-lookahead-rounds`: values kept as rows that are never
stored, a prefix network for the carries, and an in-place adder that erases its carries
with Draper's identity.

- **Rounds in place.** As in the baseline, T1 is added into h and then into d, and T2 into h.
  No register is formed afresh, so the state needs no qubits beyond the digest's.
  K + W + Σ1 + Ch is reduced to two rows that are never stored, so T1 takes two additions
  into h, not four: five additions a round in all.
- **An adder in parts of four bits.** Each part has a carry qubit per bit and a small tree
  for its propagates, and the carry into each part is kept in a qubit of its own until the
  end, when the kept carries are erased from the top down. Seven kept carries, four for
  the part, and three for the tree: 14 scratch qubits.

A round is five additions one after another. The lean entry forms each new state word from
one carry tree, with 44 more qubits.

## Rebuild and verify

`build.py` imports `../lean-lookahead-rounds/build.py` and, through it, the constants and
the hashlib check of `../example/build.py`. It checks the circuit twice: once as written,
and once without its resets, since a reset would hide scratch that was not cleared.

```bash
uv run --project ../../sha256_verifier python build.py
```

```bash
uv run --project ../../sha256_verifier sha-verify run circuit.kmb
```
