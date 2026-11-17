# In-place rounds, 786 qubits

A circuit for the reaction-depth track, made to sit on its front between
[`../zero-scratch`](../zero-scratch) and [`../lean-lookahead-rounds`](../lean-lookahead-rounds):
786 qubits at reaction depth 926, with 1,347,160 Toffolis.

| Entry | Qubits | Reaction depth |
|---|---:|---:|
| Zero scratch | 768 | 5,391 |
| In-place rounds, 775 qubits | 775 | 2,074 |
| In-place rounds, 782 qubits | 782 | 1,227 |
| **In-place rounds, 786 qubits** (this) | 786 | 926 |
| Lean lookahead rounds, 818 qubits | 818 | 667 |
| Lean lookahead rounds | 826 | 581 |

The entries between the first and the last come from one generator with different settings.
None has both fewer qubits and less depth than another.

## How it works

It reuses the generator of `../lean-lookahead-rounds`: values kept as rows that are never
stored, a prefix network for the carries, and an in-place adder that erases its carries
with Draper's identity.

- **Rounds in place.** T1 is added into d and into h, and T2 into h; no register is formed
  afresh. T1 does not go through h first: W + h + Σ1 + Ch is reduced to two rows that are
  never stored and added straight into d, so the new e waits for two additions, not five.
  K sits in the register of W for the round, which saves a row in each sum.
- **An adder in parts of eight bits.** Each part has a carry qubit per bit and a tree for
  its propagates, and the carry into each part is kept in a qubit of its own until the
  end. Eight for the part, three kept carries and seven for the tree: 18 scratch qubits.

A round's new e waits for two additions and its new a for two more. The lean entry forms
both in fresh registers from one carry tree each, with 40 more qubits.

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
