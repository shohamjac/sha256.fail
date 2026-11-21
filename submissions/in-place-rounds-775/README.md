# In-place rounds, 775 qubits

A circuit for the reaction-depth track, made to sit on its front between
[`../zero-scratch`](../zero-scratch) and [`../lean-lookahead-rounds`](../lean-lookahead-rounds):
775 qubits at reaction depth 2,074, with 1,571,904 Toffolis.

| Entry | Qubits | Reaction depth |
|---|---:|---:|
| Zero scratch | 768 | 5,391 |
| **In-place rounds, 775 qubits** (this) | 775 | 2,074 |
| In-place rounds, 782 qubits | 782 | 1,227 |
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
  No register is formed afresh, so the state needs no qubits beyond the digest's. The seven
  terms are added one at a time, each as a row that is never stored.
- **A ripple adder with pebbled carries.** The adder takes the word one bit at a time. The
  carry into a bit can be computed from the carry into the bit below at any time, from the
  two operands before that bit is added and from the operand and the sum after, and it is
  uncomputed the same way. So the carries need not all be kept: they are made and unmade
  by the rule of a reversible pebble game on a line, which gets through 31 bits with five
  carries held at once. With one qubit for the generate of the current bit and one helper,
  that is seven scratch qubits.

The price is depth and operations. A carry is made and unmade many times, and the carries
of a ripple adder wait for one another: 2,074 against 1,227 for the entry with seven more qubits.

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
