import type { ReactElement } from 'react';
import { repoFile, repoTree } from '../config';

export function Verification(): ReactElement {
  return (
    <article className="prose">
      <h1>How circuits are verified</h1>
      <p className="lede">
        A SHA-256 circuit has 2<sup>512</sup> possible inputs, so it cannot be checked on all of them. It is
        checked on about a million, chosen so that the submitter could not know them in advance.
      </p>

      <h2>What is checked</h2>
      <ol>
        <li>
          <strong>The file.</strong> It is parsed by Kickmix, written back as text, and read again by an
          independent parser. The two must agree on every count, and only a circuit rebuilt from that text is
          simulated.
        </li>
        <li>
          <strong>The structure.</strong> Exactly the required registers, of the right sizes, and only allowed
          instructions.
        </li>
        <li>
          <strong>1,179 directed tests.</strong> Fixed inputs chosen to be awkward: every single bit set and
          clear, patterns that force long carries, and padded messages of every length.
        </li>
        <li><strong>1,048,576 random tests.</strong> Uniformly random 512-bit blocks, one shot each.</li>
      </ol>
      <p>
        Every shot must end with the right digest, the block unchanged, every scratch qubit at zero and the
        phase not flipped. One failure fails the circuit.
      </p>

      <h2>What passing means</h2>
      <p>
        Passing is strong evidence, not proof. With no failures in 2<sup>20</sup> random shots, the fraction of
        inputs the circuit gets wrong is below 8.5 × 10<sup>−5</sup> at a confidence of 1 − 2<sup>−128</sup>, and
        below 2.9 × 10<sup>−6</sup> at 95%.
      </p>
      <p>
        The number of tests is therefore also the tolerance. A circuit that is wrong on one input in ten million
        would pass nine times in ten; one that is wrong on one in a hundred thousand would essentially never
        pass. There is no separate track for approximate circuits: this is the line.
      </p>

      <h2>Why the tests cannot be gamed</h2>
      <p>
        The random inputs are derived from a hash of the problem, the circuit itself, and a salt. Changing one
        gate changes every test. For results shown here, the salt is drawn at random after the circuit file is
        fixed, and recorded in the receipt.
      </p>

      <h2>Checking a result yourself</h2>
      <p>
        Every entry links to its receipt, which records the salt. Anyone can repeat the exact run, with the same
        inputs and the same simulated measurement outcomes, and must get the same receipt:
      </p>
      <pre><code>uv run sha-verify replay receipt.json circuit.kmb</code></pre>
      <p>
        The verifier, its tests and the receipt format are in the{' '}
        <a href={repoTree('sha256_verifier')}>repository</a>. The simulator is Google's Kickmix 1.0.0; the
        reference SHA-256 is checked against Python's <code>hashlib</code>. See the{' '}
        <a href={repoFile('sha256_verifier/README.md')}>verifier's README</a> for details.
      </p>
    </article>
  );
}
