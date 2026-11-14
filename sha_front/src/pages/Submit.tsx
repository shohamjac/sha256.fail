import type { ReactElement } from 'react';
import { REPO_URL, repoTree } from '../config';

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
uv run sha-verify run path/to/circuit.kmb`}</code></pre>
      <p>
        It prints a receipt and exits with status 0 if the circuit passed. On a failure the receipt names the
        check that failed and the input that broke it. While developing, <code>--shots 4096</code> gives a quick
        answer.
      </p>

      <h2>3. Open a pull request</h2>
      <p>Add one directory under <code>submissions/</code> containing:</p>
      <div className="table-scroll">
        <table>
          <thead><tr><th>File</th><th>What</th></tr></thead>
          <tbody>
            <tr><td><code>circuit.kmb</code></td><td>The circuit to verify</td></tr>
            <tr>
              <td><code>meta.json</code></td>
              <td>Name, authors, a short description, the problem id and the directory path</td>
            </tr>
            <tr>
              <td><code>build.py</code>, <code>README.md</code></td>
              <td>Optional, and welcome: how the circuit was made</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p>
        The circuit is then verified again with a salt chosen after your file is fixed, so the random tests are
        ones you could not have seen. If it passes, its receipt is committed and it appears here.
      </p>
      <p>
        Automatic verification of pull requests is not set up yet. Until it is, a maintainer runs the verifier
        on each submission by hand.
      </p>
    </article>
  );
}
