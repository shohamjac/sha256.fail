# Submissions

One directory per circuit. To submit, open a pull request that adds a new directory here.

## What to put in the directory

| File | Required | What |
|---|---|---|
| `circuit.kmb.zst` (or `circuit.kmx.zst`, `circuit.kmb`, `circuit.kmx`) | yes, exactly one | The Kickmix circuit to verify. A file over 1 MiB must be zstd-compressed (below). |
| `meta.json` | yes | Who made it and what it is (below) |
| `README.md`, `build.py`, anything else | no | How the circuit was made. Welcome, and never executed. |

The directory name is 1 to 64 lower-case letters, digits and hyphens.

Circuit files compress very well (a 32 MB `.kmb` becomes about 0.5 MB), so circuits are
committed compressed to keep the repository small. The verifier does it for you, no other
tool needed:

```bash
uv run sha-verify pack circuit.kmb --rm   # writes circuit.kmb.zst and removes circuit.kmb
```

The plain `zstd -19 circuit.kmb` command works too. Every verifier command reads the
compressed file directly.

### `meta.json`

```json
{
  "name": "Short name shown on the leaderboard",
  "authors": ["Your name or handle"],
  "github_user_id": 1234567,
  "kind": "submission",
  "problem": "sha256-compress-v1",
  "path": "submissions/your-directory",
  "description": "A few sentences on how the circuit works and what is new in it."
}
```

All fields but `github_user_id` are required. `kind` must be `submission`, and `path` must
be the directory the file is in. Also optional: `source` (the generator file, such as `build.py`), `reference`
(a URL), and `links` (a list of URLs). Other fields are rejected.

`github_user_id` puts your GitHub profile picture next to the submission on the leaderboard.
It is the numeric ID of your GitHub account, not your username: find it with
`gh api user --jq .id`, or at `https://api.github.com/users/<your-username>`. It must be the
account that opens the pull request. Leave the field out to stay anonymous; the bot's comment
then tells you your ID, in case you change your mind.

## What happens to a pull request

1. **It is checked automatically.** The pull request must add exactly one new directory here
   and touch nothing else. A bot verifies the circuit at full strength, with a random salt
   drawn after your file is fixed, and comments the result: qubits, Toffolis, reaction
   depth, the score on each track, and whether it is on each Pareto front. If the circuit fails, the comment names the check and
   the input that broke it.
2. **A maintainer merges it.**
3. **The official receipt is recorded.** On merge the circuit is verified once more with a
   new salt, the receipt is committed to `results/`, and the site is rebuilt. That receipt
   is the one that counts. A circuit that is wrong on a small fraction of inputs can pass one
   run and fail the other.

To change a submission, add a new directory; existing ones are not edited through pull
requests.

Nothing in a submission is ever executed. The verifier reads the circuit file and
`meta.json`, and nothing else.

## Check it yourself first

```bash
cd sha256_verifier
uv sync --locked
uv run sha-verify check-submission ../submissions/your-directory --external
uv run sha-verify run ../submissions/your-directory/circuit.kmb.zst
```

## What is here

| Directory | What |
|---|---|
| `example/` | The baseline: a plain, readable construction and a starting point |
| `low-qubit-adder/`, `compute-copy-uncompute/` | Variants of the baseline by the project |
| `literature-*/` | Reconstructions of published circuits by the project |
