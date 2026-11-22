# Problem `bitcoin-mining-v1`

> **Draft.** The verifier implements this problem (`sha-verify run --problem
> bitcoin-mining-v1`), but the track is not open and the problem may still change. Once the
> track opens, this document is frozen like `sha256-compress-v1`: any change to the
> registers, bit order, function, allowed instructions or tests is a new problem with a new
> name.

A phase oracle for Bitcoin mining: flip the phase when a block's hash is below the target,
and do nothing otherwise.

This is the oracle Grover's algorithm needs to mine. The block holds only the coinbase
transaction, so the merkle root is the coinbase's transaction id and there is no merkle
tree. The search register is 80 qubits: 6 bytes of the coinbase and the 4-byte header nonce.
The header's own free fields are too few for a search at today's difficulty, which is why
the coinbase is inside the oracle.

The oracle takes one input Bitcoin does not have, a classical `mask` that is XORed into the
hash before the comparison. With a mask of zero the oracle is Bitcoin's check. The mask is
what lets the tests reach hits and near misses at real difficulty on inputs nobody has seen.

## The function

`compress` and `IV` are those of [`sha256-compress-v1`](sha256-compress-v1.md), except that
`compress(state, block)` here takes its starting state as an argument. `‖` joins byte
strings, and a 256-bit state or digest is also read as 32 bytes, `H_0` first.

```
inner1 = compress(midstate, extranonce ‖ tail)                              coinbase, last block
root   = compress(IV, inner1 ‖ pad256)                                      merkle root
mid    = compress(IV, version ‖ prev_hash ‖ root[0:28])                     header, first block
inner2 = compress(mid, root[28:32] ‖ time ‖ bits ‖ nonce ‖ pad640)          header, second block
hash   = compress(IV, inner2 ‖ pad256)                                      block hash
masked = hash[0:20] ‖ (hash[20:32] XOR mask)                                H_5, H_6, H_7 masked
```

`pad256` is the SHA-256 padding of a 32-byte message (`80`, 23 bytes of `00`, then
`00 00 00 00 00 00 01 00`), and `pad640` that of an 80-byte message (`80`, 39 bytes of `00`,
then `00 00 00 00 00 00 02 80`). Both are constants.

Read `masked` as a 256-bit integer `v`, least significant byte first, as Bitcoin reads a
block hash. The target comes from `bits` in Bitcoin's compact form, an exponent `e` and a
mantissa `M`:

`f = 1` when `v < M · 256^(e − 3)`, and `0` otherwise.

The circuit must act as `|extranonce, nonce⟩ → (−1)^f |extranonce, nonce⟩`. Nothing else is
left behind: there is no output register.

The inputs are always in this range, and what the circuit does outside it is not tested:

- `bits` has `0x17 ≤ e ≤ 0x20` and `1 ≤ M ≤ 0x7fffff`. Bitcoin's main network has used every
  exponent from `0x1d` (2009) down to `0x17` (today); `0x1e` to `0x20` are easier than any
  real block.
- `tail` is the end of a padded message: between 0 and 49 message bytes, then `80`, zeros,
  and the message length in bits as 8 bytes. With the 6 bytes of `extranonce`, the
  coinbase's last block holds 6 to 55 message bytes.

### Differences from Bitcoin

- **The mask.** Bitcoin has none; it is the case `mask = 0`. Without a mask, an input that
  meets a target at exponent `0x17` costs about 2^79 hashes to find, so the only such inputs
  are mined blocks, and those are public. With it, the tests take any input, compute its
  hash, and choose the mask that puts the compared value wherever they want. The mask costs
  a circuit no Toffolis: XOR with a classical bit is an `X` under a condition.
- **`<` instead of `≤`.** Bitcoin accepts a block whose hash equals the target. The two
  rules differ on that one value of the hash. With `<` the answer depends only on
  `⌊v / 256^(e − 3)⌋`, the bits of the hash from the mantissa upwards. For every allowed
  exponent these lie in `H_5`, `H_6` and `H_7`, so a circuit never needs `H_0 … H_4` of the
  last compression, and the mask covers exactly the bits that matter.
- **Only the proof of work is checked.** Whether the coinbase is a valid transaction, and
  every other consensus rule, is outside the oracle.

## Registers

A circuit declares exactly these nine registers, in this order:

| Register | Made of | Holds | At the end |
|---|---|---|---|
| `extranonce` | 48 distinct qubits | bytes 0–5 of the coinbase's last block | unchanged |
| `nonce` | 32 distinct qubits | header bytes 76–79 | unchanged |
| `midstate` | 256 classical bits | SHA-256 state before the coinbase's last block | any state |
| `tail` | 464 classical bits | bytes 6–63 of the coinbase's last block | any state |
| `version` | 32 classical bits | header bytes 0–3 | any state |
| `prev_hash` | 256 classical bits | header bytes 4–35 | any state |
| `time` | 32 classical bits | header bytes 68–71 | any state |
| `bits` | 32 classical bits | header bytes 72–75: hashed, and read as the target | any state |
| `mask` | 96 classical bits | XORed into `H_5`, `H_6`, `H_7` of the block hash | any state |

No qubit or bit is shared between registers. Every other qubit is scratch: it starts as
zero and must end as zero. Other classical bits start as zero. Classical bits are not
counted and may end in any state.

The circuit reads classical registers through conditions (`X q5 if b3`,
`PUSH_CONDITION if b3`). It may overwrite them and compute on them classically.

## Bit order

Every register except `midstate` and `mask` is a run of bytes of one SHA-256 message block.
Split that block into words `W_0 … W_15` as FIPS 180-4 does (big-endian over bytes); bit 0
is the least significant bit of a word.

| Register | Block | Offsets |
|---|---|---|
| `extranonce` | coinbase, last | `[k]` is bit `k` of `W_0` for `k < 32`; `[32 + k]` is bit `16 + k` of `W_1` for `k < 16` |
| `tail` | coinbase, last | `[k]` is bit `k` of `W_1` for `k < 16`; `[16 + 32·(j − 2) + k]` is bit `k` of `W_j` for `j = 2 … 15` |
| `version` | header, first | `[k]` is bit `k` of `W_0` |
| `prev_hash` | header, first | `[32·j + k]` is bit `k` of `W_(1+j)` for `j = 0 … 7` |
| `time` | header, second | `[k]` is bit `k` of `W_1` |
| `bits` | header, second | `[k]` is bit `k` of `W_2` |
| `nonce` | header, second | `[k]` is bit `k` of `W_3` |

`midstate[32·j + k]` is bit `k` of state word `j`.

`mask[32·j + k]` is XORed into bit `k` of `H_(5+j)` of the block hash, for `j = 0, 1, 2`.
In terms of the integer `v`: bit `p` of `v`, for `160 ≤ p ≤ 255`, is masked by
`mask[32·(i // 4 − 5) + 8·(3 − i % 4) + p % 8]` with `i = p // 8`.

Bitcoin stores `version`, `time`, `bits` and `nonce` least significant byte first, so each
of these words is the byte swap of the number Bitcoin shows. For the word `T` of `bits`:

- `e = T & 0xff`, which is `bits[0 … 7]`
- `M = (T >> 24) | ((T >> 8) & 0xff00) | ((T << 8) & 0xff0000)`

The merkle root goes into the header as the raw digest bytes, with no reversal: `H_0 … H_6`
of `root` are `W_9 … W_15` of the header's first block, and `H_7` is `W_0` of its second.

The hash is compared least significant byte first, so the most significant byte of `v` is
the last byte of the digest, which is the low byte of `H_7`.

## From a real block to inputs

Take a block whose only transaction is the coinbase, and whose coinbase, serialized without
witness data, has a length `n` with `6 ≤ n mod 64 ≤ 55`.

1. Pad the coinbase as SHA-256 does and split it into 64-byte blocks.
2. `midstate` is the state after compressing every block but the last, starting from `IV`.
3. `extranonce` is the first 6 bytes of the last block and `tail` the other 58.
4. `version`, `prev_hash`, `time`, `bits` and `nonce` are the header's fields as stored.
5. `mask` is zero.

The function's `root` is then the block's merkle root, its `hash` the block's hash, and its
target the block's target.

The 6 bytes called `extranonce` are whatever the coinbase has at that position. They are
not the bytes the block's miner varied.

## Phase

Kickmix's simulator runs each shot on one basis state and keeps one sign for it. A shot
must end with the sign flipped when `f = 1` and not flipped when `f = 0`. The sign is
absolute: `NEG` flips it.

The simulator has no superpositions, and the test does not need them. The oracle is
diagonal with entries +1 and −1, so its sign on every basis state is all there is to it.

## Allowed instructions

The same as `sha256-compress-v1`, every Kickmix 1.0.0 instruction except `Z_POW`.

## Cost

- **Q**, qubits: the highest qubit index used, plus one. Classical bits do not count, so Q
  is at least 80.
- **C**, Toffolis: the mean number of `CCX`, `CCZ` and `CSWAP` instructions executed per
  shot of the random tests, as in `sha256-compress-v1`. An instruction under a classical
  condition counts only in the shots where the condition holds.
- **Score**: Q × C. Lower is better.

The receipt also records the number of these instructions in the circuit text, as
`circuit.toffoli_static`. It is not scored. The two numbers are equal unless the circuit
puts Toffolis under classical conditions.

A circuit can read the exponent, and at an easy exponent it needs less of the hash: at
`0x20` only `H_7`. The random tests use the ten exponents equally, so for a circuit that
skips work this way C is its average over the ten, not its cost at today's exponent.

### Reaction-depth track

As in `sha256-compress-v1`: D is what `Circuit.reaction_depth()` of Kickmix 1.0.0 returns,
and the score is Q × D. Input bits have depth zero.

## Verification

A shot passes when the phase is flipped exactly when `f = 1`, `extranonce` and `nonce` are
unchanged and scratch is at zero. A shot with the wrong phase fails with the code
`wrong_phase`.

### Directed tests: real blocks

A fixed list of coinbase-only blocks from Bitcoin's main network, at least two for each
exponent from `0x1d` to `0x17`. For each block:

| Shots | Inputs | Mask | Phase |
|---:|---|---|---|
| 1 | the block | zero | flipped |
| 1 | the block with its nonce, as a number, increased by one | zero | not flipped |
| 80 | the block with one bit of `extranonce` or `nonce` flipped | zero | not flipped |
| 96 | the block | one bit set | as the function gives |

A one-bit mask keeps the hit when the bit is below the mantissa, removes it when the bit is
above the mantissa, and inside the mantissa does either.

The shots run block by block in the order of the table below, and within a block in the
order of the rows above: bits of `extranonce` before bits of `nonce`, each from offset 0 up.
They are 2,848 shots, of which 635 expect a flip.

The blocks' headers and coinbase transactions are in `src/sha_verifier/bitcoin_blocks.py`.
They were taken from a public block explorer, and the verifier's tests check them with
`hashlib`: each coinbase hashes to the merkle root in its header, and each header's hash
meets the target in the header.

| Height | `bits` | Coinbase bytes | Leading zero bits of the hash | One-bit masks that keep the hit |
|---:|---|---:|---:|---:|
| 20013 | `1d00ffff` | 134 | 33 | 64 |
| 20014 | `1d00ffff` | 134 | 32 | 64 |
| 69013 | `1c0168fd` | 134 | 41 | 57 |
| 69014 | `1c0168fd` | 135 | 41 | 57 |
| 100006 | `1b04864c` | 135 | 48 | 50 |
| 100007 | `1b04864c` | 134 | 47 | 50 |
| 199962 | `1a05db8b` | 142 | 53 | 42 |
| 199976 | `1a05db8b` | 142 | 54 | 42 |
| 279709 | `1903071f` | 175 | 63 | 33 |
| 279737 | `1903071f` | 176 | 62 | 33 |
| 419501 | `180526fd` | 146 | 73 | 27 |
| 419904 | `180526fd` | 173 | 71 | 27 |
| 739788 | `17096a20` | 236 | 81 | 20 |
| 739815 | `17096a20` | 309 | 78 | 19 |
| 976830 | `17021673` | 291 | 79 | 17 |
| 976835 | `17021673` | 289 | 80 | 17 |

### Random tests

2^20 = 1,048,576 shots. In each:

- `midstate`, `version`, `prev_hash`, `time`, `extranonce` and `nonce` are uniformly random.
- `tail` is the end of a padded message of `64·k + L` bytes, with `L` uniform in 6 … 55,
  `k` uniform in 1 … 8, and uniformly random message bytes.
- `bits` holds an exponent `e` uniform in `0x17` … `0x20` and a mantissa `M` whose length is
  uniform in 1 … 23 bits and which is uniform among the mantissas of that length.

The verifier computes the shot's hash and then chooses the mask. Write
`q = ⌊v / 256^(e − 3)⌋` for the masked hash, so that `f = 1` exactly when `q < M`. The mask
is the one that gives `q` the value below and makes every masked bit under the mantissa
uniformly random. The value depends on the shot's index `i`:

| `i mod 16` | Share | `q` | Phase |
|---|---:|---|---|
| 0 – 5 | 3/8 | uniform in `0 … M − 1` | flipped |
| 6 – 7 | 1/8 | `M − 1` | flipped |
| 8 – 9 | 1/8 | `M` | not flipped |
| 10 – 11 | 1/8 | uniform in `M … 0x7fffff` | not flipped |
| 12 – 14 | 3/16 | uniform in `0 … M − 1`, with one more bit set, uniform among the bits of `q` from 23 up | not flipped |
| 15 | 1/16 | no value: the mask is uniformly random | flipped in about 1 shot in 300, nearly all at `0x20` |

The expected phase always comes from the function, not from this table. Half the shots,
about 524,000, expect a flip, spread evenly over the ten exponents.

The mask alone says nothing about which row a shot is in: it is the wanted value XORed with
the hash, and the circuit does not know the hash until it has computed it.

The inputs and all the choices above are derived from
`SHA-256(problem name, circuit hash, salt)`, so they depend on the circuit and cannot be
known before it is fixed. Each shot takes 199 bytes of the random stream; the rule that
turns them into the inputs is at the top of `src/sha_verifier/bitcoin.py`. A uniform choice
among `n` options is a 64-bit integer modulo `n`.

### What passing shows

Passing is evidence, not proof.

- **The hashing and the comparison are right at every exponent, on inputs nobody has seen.**
  Zero failures in about 524,000 shots that expect a flip bound the fraction of inputs and
  masks on which the circuit misses a hit below 1.7 × 10^-4, at confidence 1 − 2^-128. For
  one exponent alone the bound is 1.7 × 10^-3. The same holds for false hits.
- **The mantissa is compared exactly.** A quarter of the shots sit at `M − 1` or `M`, the
  two values on either side of the target.
- **Every bit above the mantissa is checked.** In rows 12 – 14 the hash would meet the
  target but for one bit. At exponent `0x17` there are 73 such bits and each gets about 270
  shots.
- **Real blocks are accepted.** Each listed block flips the phase with a mask of zero,
  which for the latest blocks is Bitcoin's check at today's difficulty.

What it does not show:

- **A mask of zero on inputs nobody has seen.** Random masks are never zero, so at real
  difficulty the unmasked oracle is tested on the listed blocks alone, and a circuit could
  recognise those from its classical inputs. A circuit that treats a zero mask differently
  gains nothing by it: it must still pass the masked tests, and its score comes from them
  alone. No test can exclude it.
- **Errors rarer than the bounds above.**
- **`hash = target`**, where this function and Bitcoin's rule differ.

## Limits

The same as `sha256-compress-v1`: at most 512 MiB, 20,000,000 operations, 65,536 qubits and
1,048,576 classical bits.

## Test vectors

Block 1 of Bitcoin's main network (hash `00000000839a8e68…18eb6048`, coinbase of 134
bytes). Every value is a byte string in hex, in message order.

| Input | Value |
|---|---|
| `midstate` | `0a066bebb4720ae534b6849209f878edd4ff18e00c2a340494d672b420907ac5` |
| `extranonce` | `eeac00000000` |
| `tail` | `80`, 55 bytes of `00`, `04 30` |
| `version` | `01000000` |
| `prev_hash` | `6fe28c0ab6f1b372c1a6a246ae63f74f931e8365e15a089c68d6190000000000` |
| `time` | `61bc6649` |
| `bits` | `ffff001d` |
| `nonce` | `01e36299` |

The target is `e = 0x1d`, `M = 0x00ffff`, so the mantissa covers bits 208 to 230 of `v`.
Unmasked, `q = 0x00839a`. The mask's 12 bytes line up with bytes 20 to 31 of the hash,
which are `5159ab86 688e9a83 00000000`.

| `mask` | Meaning | Phase |
|---|---|---|
| `00000000 00000000 00000000` | the block as mined | flipped |
| `00000000 0000647c 00000000` | `q` becomes `M − 1 = 0x00fffe` | flipped |
| `00000000 0000657c 00000000` | `q` becomes `M = 0x00ffff` | not flipped |
| `00000000 00000000 80000000` | bit 231, the lowest bit above the mantissa | not flipped |
| `00000000 00000000 00000080` | bit 255, the top bit | not flipped |
| `ffffffff ffff0000 00000000` | every masked bit below the mantissa | flipped |
| zero, with `nonce` = `02e36299` | the nonce increased by one | not flipped |
