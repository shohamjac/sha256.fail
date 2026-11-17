# Carry-lookahead rounds

A circuit for the reaction-depth track. On that track Toffolis are free, so this one spends
them to shorten the chains that reaction depth measures.

| | This | Trimmed constants and tail | Zero scratch |
|---|---:|---:|---:|
| Qubits (Q) | 1,006 | 829 | 768 |
| Reaction depth (D) | 629 | 3,892 | 5,391 |
| Score (Q × D) | 632,774 | 3,226,468 | 4,140,288 |

The score is 5.1 times lower than the previous best on the depth track. It uses 1,151,702
Toffolis, so it is far off the front on the Toffoli track.

## What reaction depth counts

Kickmix tracks two depths per qubit. Its x depth is when it is known whether the qubit owes
an X correction: only a Toffoli adds to it, so it is the AND-depth of the value. Its z depth
is when it is known whether it owes a Z: it flows backwards through CNOTs, from target to
control, and a measurement's result is one deeper than the measured qubit's z depth. A
measurement-based uncomputation puts that result back onto the inputs as a phase correction.

In the previous best, z sets the depth: 3,892 against an x depth of 2,407. Each ripple
adder's carries are cleared from the top bit down, and every carry waits for the one above
it. Adding into the same registers round after round chains those waits.

Two facts this circuit relies on:

- A qubit that is reset carries no depth. Ancillas can be reused at no cost, and only data
  dependencies count.
- An in-place addition `b += a` passes b's depth on to a's phase corrections. When the target
  is long-lived, that chains from round to round. An addition into a fresh register does not.

## How it works

- **Carry-lookahead adders.** Every addition uses a Sklansky prefix network, AND-depth 6
  instead of 31 for a ripple adder. The carries are written into the sum and then erased
  using Draper's identity carries(a, b) = carries(a, ~(a + b)). Running the network backwards
  on (a, ~s) turns them back into a & ~s, which is cleared by measurement. Each group
  propagate is built from transient qubits when a step needs it, and unbuilt at once. So the
  adder keeps only its 31 carries, plus at most 15 transients.
- **Carry-save rounds into fresh registers.** Each round computes
  e' = d + h + W + K + Σ1(e) + Ch(e, f, g) and a' = h + W + K + Σ1(e) + Ch + Σ0(a) + Maj(a, b, c)
  into new registers. Each is one carry-save tree followed by one carry-lookahead addition. The
  tree combines the earliest terms first, using the depth it tracks while building. Per round
  that is about 7 AND levels: Ch, one carry-save carry, then the adder.
- **Only carry rows are stored.** A value is kept as a polynomial over qubits: per bit, an XOR
  of products of one or two qubits. Σ0, Σ1, W, K and the sums of the carry-save tree are
  linear, and Ch and Maj are degree 2, so none of them is stored. When a Toffoli needs such a
  bit, a helper qubit is built, used, unbuilt and reset. A carry of three early linear terms
  also stays virtual.
- **The dropped registers are measured, not subtracted.** The registers for d and h are not
  needed after the round. They are measured in the X basis, and the phase correction goes on
  a fresh recomputation of their value from registers that remain:

      d = e' - a' + Σ0(a) + Maj(a, b, c)
      h = a' - W - K - Σ1(e) - Ch(e, f, g) - Σ0(a) - Maj(a, b, c)

  The recomputation is an out-of-place sum, uncomputed straight after. No state register is
  ever the target of an addition, and the two erasures don't depend on each other. Erasing d
  through h instead (d = e' - h - W - K - Σ1 - Ch) chains them: depth 771 instead of 630, in a
  version a little earlier than this one.
- **Schedule.** As in the baseline, W_t overwrites W_(t-16) in `block` and is rewound at the
  end. Each word takes three in-place additions, ordered so that the operand whose register is
  updated next goes first, and the operand that is ready last goes last. Combining the three
  operands with a carry-save sum first was worse (depth 751): it doubles the phase chain each
  step passes on. That was in an earlier version, where the separate additions took depth from
  751 to 633.
- **First rounds.** State words that are still constants (rounds 0 to 3) are kept as
  constants. The 256 digest qubits serve as scratch until the result is ready, and the digest
  register is declared on whichever registers hold it at the end.

## Where the depth goes

| Part | Depth |
|---|---:|
| 64 rounds, about 7.3 each | 480 |
| Feed-forward and the rewind of the schedule | 149 |
| Total | 629 |

The rewind is a chain: undoing W_t needs W_(t-2), which is undone next. That gives 23 hops of
about 6, the phase chain of one adder each.

Qubits: 768 for the registers, 64 for the two new state registers held while the old ones are
erased, about 128 for the carry rows of the a' sum, and 46 for the adder.

## Tried, and not used

Measured on versions a little earlier than this one, at about 1,006 to 1,038 qubits and
depth 630 to 633.

- **Adding W + K into h in place first**, which saves two stored carry rows. It reintroduces
  the round-to-round phase chain: depth 849.
- **Not storing W_62 and W_63**, as `../trimmed-constants-and-tail` does. Depth falls by up to
  10, but the extra terms need a stored carry row: 32 more qubits.
- **Virtual carries for late terms.** This saves 64 qubits but adds an AND level per round:
  974 × 689.

## Rebuild and verify

`build.py` imports the constants and the hashlib check from `../example/build.py`. It checks
the circuit twice: once as written, and once without its resets, since a reset would hide
scratch that was not cleared.

```bash
uv run --project ../../sha256_verifier python build.py
```

```bash
uv run --project ../../sha256_verifier sha-verify pack circuit.kmb --rm
```

```bash
uv run --project ../../sha256_verifier sha-verify run circuit.kmb.zst
```
