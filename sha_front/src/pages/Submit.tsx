import type { ReactElement } from 'react';
import { REPO_URL, repoFile, repoTree } from '../config';

export function Submit(): ReactElement {
  return (
    <article className="prose">
      <h1>Submit a circuit</h1>
      <p className="lede">
        A submission is a circuit file, not a program. Nobody runs your code: the verifier reads the file and
        simulates it.
      </p>

      <h2>1. Build a circuit</h2>
      <p>
        Produce a Kickmix circuit file, <code>circuit.kmb</code> (binary) or <code>circuit.kmx</code> (text), that
        meets <a href="#/rules">the task</a>. The <a href={repoTree('submissions/example')}>baseline submission</a>{' '}
        is a readable starting point: its <code>build.py</code> generates the whole circuit with Kickmix's Python
        builder in about two hundred lines.
      </p>

      <h2>2. Verify it yourself</h2>
      <p>The verifier is in the repository. A full run takes about a minute on one core.</p>
      <pre><code>{`git clone ${REPO_URL}
cd sha256.fail/sha256_verifier
uv sync --locked
uv run sha-verify run path/to/circuit.kmb
uv run sha-verify pack path/to/circuit.kmb --rm`}</code></pre>
      <p>
        It prints a receipt and exits with status 0 if the circuit passed. On a failure the receipt names the
        check that failed and the input that broke it. While developing, <code>--shots 4096</code> gives a quick
        answer. The last line compresses the circuit to <code>circuit.kmb.zst</code>, often 50 to 200 times smaller,
        which is how it is submitted; every verifier command reads the compressed file directly.
      </p>

      <h2>3. Open a pull request</h2>
      <p>Add one directory under <code>submissions/</code> containing:</p>
      <div className="table-scroll">
        <table>
          <thead><tr><th>File</th><th>What</th></tr></thead>
          <tbody>
            <tr><td><code>circuit.kmb.zst</code></td><td>The circuit to verify, zstd-compressed (required over 1 MiB)</td></tr>
            <tr>
              <td><code>meta.json</code></td>
              <td>
                Name, authors, a short description, the problem id and the directory path; optionally your
                numeric GitHub user ID, to show your profile picture on the leaderboard. The fields are
                listed in the <a href={repoFile('submissions/README.md')}>submissions guide</a>.
              </td>
            </tr>
            <tr>
              <td><code>build.py</code>, <code>README.md</code></td>
              <td>Optional, and welcome: how the circuit was made</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p>
        The pull request must add that one directory and nothing else. Within a few minutes a bot verifies the
        circuit at full strength, with a salt drawn after your file is fixed, so the random tests are ones you
        could not have seen. It comments the result on the pull request: qubits, Toffolis, reaction depth, the
        score on each track, and whether the circuit is on each Pareto front. If the circuit fails, the comment names the check and the input
        that broke it.
      </p>

      <h2>4. Merge</h2>
      <p>
        When a maintainer merges the pull request, the circuit is verified once more with a new salt. That
        receipt is committed to the repository and is the one that counts; the site is rebuilt and the circuit
        appears here.
      </p>
    </article>
  );
}
