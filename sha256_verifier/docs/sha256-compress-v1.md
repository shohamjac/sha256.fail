# Problem `sha256-compress-v1`

One SHA-256 compression: given a 512-bit block, write the 256-bit result of compressing it
from the standard initial hash value.

This document is the contract. It is frozen: any change to the registers, bit order,
function, allowed instructions or directed tests is a new problem with a new name.
The code that defines it is `sha_verifier.problems.SHA256_COMPRESS_V1`.

## The function

`digest = compress(IV, block)`, where `compress` is the SHA-256 compression function of
FIPS 180-4 §6.2.2 — message schedule, 64 rounds, and the final addition of the input
chaining value — and `IV` is the standard initial hash value `6a09e667 … 5be0cd19`.

The block is arbitrary: all 512 bits are inputs and there is no padding. When the block
happens to be a padded message of at most 55 bytes, `digest` is the SHA-256 of that message.

## Registers

A circuit declares exactly these two registers, in this order, each made of distinct qubits
with no qubit shared between them:

| Register | Qubits | At the start | At the end |
|---|---:|---|---|
| `block` | 512 | the input | unchanged |
| `digest` | 256 | all zero | `compress(IV, block)` |

Every other qubit is scratch: it starts as zero and must end as zero. Classical bits start
as zero, are not counted, and may end in any state.

The circuit is only ever run with `digest` and scratch starting at zero. What it does
otherwise is not tested, so it may use the `digest` qubits as workspace.

## Bit order

Split the block into sixteen 32-bit words `W_0 … W_15` and the digest into eight words
`H_0 … H_7`, exactly as FIPS 180-4 does (big-endian over bytes). Then:

- `block[32·j + k]` is bit `k` of `W_j`
- `digest[32·j + k]` is bit `k` of `H_j`

where bit 0 is the least significant bit of the word. Each word is little-endian within its
register, which is Kickmix's convention for integers, so `block[32j : 32j+32]` can be passed
to an adder as it is.

In terms of bytes: bit `b` (7 is the most significant) of byte `i` of the block is at
register offset `32·(i // 4) + 8·(3 − i % 4) + b`. The same formula gives digest offsets.

Example — the padded empty message, block bytes `80 00 00 … 00`: `W_0 = 0x80000000`, so
the only qubit set is `block[31]`. Its digest is `e3b0c442 98fc1c14 …`; `H_0 = 0xe3b0c442`
has bits 1, 6, 10, 14, 15, 20, 21, 23, 24, 25, 29, 30, 31 set, so those offsets of `digest`
are set, and so on for `H_1 … H_7` at offsets 32 and up.

## Phase

A run must not end with its phase flipped. A measurement-based uncomputation whose phase
correction is missing or wrong flips the phase on about half of the shots it affects.

## Allowed instructions

Every Kickmix 1.0.0 instruction except `Z_POW`:

`X` `CX` `CCX` `SWAP` `CSWAP` `Z` `CZ` `CCZ` `NEG` `R` `HMR` `BIT_INVERT` `BIT_STORE0`
`BIT_STORE1` `PUSH_CONDITION` `POP_CONDITION` `REGISTER` `APPEND_TO_REGISTER` `DEBUG_PRINT`
`INFO_TAG`

Measurement-based uncomputation (`HMR`, `R`, classically conditioned gates) is allowed.

## Cost

- **Q**, qubits: the highest qubit index used, plus one. Registers and scratch all count.
- **C**, Toffolis: the mean number of `CCX`, `CCZ` and `CSWAP` instructions executed per
  shot. An instruction under a classical condition counts only in the shots where the
  condition holds.
- **Score**: Q × C. Lower is better.

### Reaction-depth track

A second ranking replaces C with the circuit's reaction depth. The circuits and their
verification are the same; only the scoring differs.

- **D**, reaction depth: what `Circuit.reaction_depth()` of Kickmix 1.0.0 returns for the
  circuit. The receipt records it as `circuit.reaction_depth`.
- **Score**: Q × D. Lower is better.

Reaction depth is the longest chain of measurement results a fault-tolerant computer must
wait for, one after another, to keep track of the Pauli corrections the circuit owes. On a
machine with enough magic-state factories it sets the runtime. Kickmix tracks, for each
qubit, how many reactions must pass before it is known whether that qubit owes an X, and
whether it owes a Z, plus a depth for each classical bit:

- Clifford gates (`X`, `Z`, `CX`, `CZ`, `SWAP`) add no reactions; they only carry
  dependencies from one qubit to another.
- `CCX`, `CCZ` and `CSWAP` each add one reaction to the corrections they create. Kickmix
  models each as an auto-corrected Toffoli, so four Toffolis in a row, each failing to
  commute with the next, have depth 2, not 4.
- `HMR` adds one reaction: its bit is one deeper than the qubit's Z depth.
- A gate under a classical condition is at least as deep as its condition bit.
- `R` and `HMR` clear a qubit's depths, and a new measurement or `BIT_STORE0`/`BIT_STORE1`
  replaces a bit's depth. D is the largest depth left at the end of the circuit, so depth
  that nothing later depends on does not count.

Unlike C, D is a property of the circuit text: a conditional instruction counts whether or not
a given shot runs it. Kickmix's source:
[`compute_reaction_depth`](https://github.com/quantumlib/Qualtran/blob/main/kickmix/src/kickmix/circuit/circuit_util.cc).
The idea is from Craig Gidney's talk "How to eat magic states" (APS March Meeting 2026).

## Verification

A circuit passes when every shot below ends with the right `digest`, `block` unchanged,
scratch at zero, and phase not flipped.

1. **Directed tests**: 1,179 fixed blocks, defined by `problems.SHA256_COMPRESS_V1.directed_inputs`:
   8 constant patterns; each of the 512 bits set alone; each of the 512 bits clear alone;
   each word all ones alone, and all zeros alone; two blocks that make the first sixteen
   additions carry fully (`W_t = −K_t` and `W_t = ¬K_t`); and 113 padded messages covering
   every message length from 0 to 55 bytes.
2. **Random tests**: 2^20 = 1,048,576 uniformly random blocks, one shot each.

The random blocks are derived from `SHA-256(problem name, circuit hash, salt)`, so they
depend on the circuit and cannot be known before it is fixed. A run with the same circuit and
salt always uses the same blocks and the same measurement outcomes.

Passing is evidence, not proof. Zero failures in 2^20 random shots bounds the failure rate
below 8.5 × 10^-5 at confidence 1 − 2^-128. A circuit that is wrong on one input in ten
million would pass nine times in ten.

## Limits

A submission may be at most 512 MiB, 20,000,000 operations, 65,536 qubits and 1,048,576
classical bits. These are resource limits of the verifier, set far above what the task needs.

## Test vectors

Block and digest as byte strings in hex.

| Block | Digest |
|---|---|
| 64 bytes of `00` | `da5698be17b9b46962335799779fbeca8ce5d491c0d26243bafef9ea1837a9d8` |
| 64 bytes of `ff` | `ef0c748df4da50a8d6c43c013edc3ce76c9d9fa9a1458ade56eb86c0a64492d2` |
| bytes `00 01 02 … 3f` | `fc99a2df88f42a7a7bb9d18033cdc6a20256755f9d5b9a5044a9cc315abe84a7` |
| `61 62 63 80`, 59 bytes of `00`, `18` (padded "abc") | `ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad` |
| `80`, 63 bytes of `00` (padded empty message) | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

The directed test set is pinned by fingerprint in `tests/test_problems.py`.
