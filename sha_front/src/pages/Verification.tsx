import type { ReactElement } from 'react';
import { repoFile, repoTree } from '../config';

export function Verification(): ReactElement {
  return (
    <article className="prose">
      <h1>How circuits are verified</h1>
      <p className="lede">
        A circuit has far too many possible inputs to be checked on all of them: 2<sup>512</sup> for SHA-256
        compression. It is checked on about a million, chosen so that the submitter could not know them in
        advance.
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
          <strong>Directed tests.</strong> Fixed inputs chosen to be awkward.
          <ul>
            <li>
              SHA-256 compression: 1,179 of them. Every single bit set and clear, patterns that force long
              carries, and padded messages of every length.
            </li>
            <li>
              Bitcoin mining oracle: 2,848 of them, made from 16 real blocks of Bitcoin's main network, at
              least two at each difficulty exponent the network has used. The block as mined must flip the
              phase. The block with its nonce one higher, or with any one bit of the search register flipped,
              must not. The block with each single bit of the mask set must do what the function says.
            </li>
          </ul>
        </li>
        <li>
          <strong>1,048,576 random tests.</strong> One shot each.
          <ul>
            <li>SHA-256 compression: uniformly random 512-bit blocks.</li>
            <li>
              Bitcoin mining oracle: random block contents at all ten difficulty exponents, with the mask
              chosen so that half the shots meet the target. A quarter of all shots sit on the target or on
              the value just below it, and three in sixteen would meet the target but for one bit.
            </li>
          </ul>
        </li>
      </ol>
      <p>
        Every shot must end with the right answer, the input qubits unchanged and every scratch qubit at zero.
        For SHA-256 compression the answer is the digest, and the phase must not be flipped. For the Bitcoin
        mining oracle the answer is the phase, flipped exactly when the hash is below the target. One failure
        fails the circuit.
      </p>

      <h2>What passing means</h2>
      <p>
        Passing is strong evidence, not proof. With no failures in 2<sup>20</sup> random shots, the fraction of
        inputs the circuit gets wrong is below 8.5 × 10<sup>−5</sup> at a confidence of 1 − 2<sup>−128</sup>, and
        below 2.9 × 10<sup>−6</sup> at 95%.
      </p>
      <p>
        For the Bitcoin mining oracle a missed hit and a false hit are bounded separately, each by the half of
        the shots that could show it: either happens on less than 1.7 × 10<sup>−4</sup> of inputs and masks, at
        the same confidence of 1 − 2<sup>−128</sup>. One thing stays untested there. At today's difficulty the
        oracle with a mask of zero is run on the real blocks alone, since nobody can make another input that
        hits; <a href="#/bitcoin">Quantum Bitcoin mining</a> explains why the masked tests stand in for it.
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
      <pre><code>uv run sha-verify replay receipt.json circuit.kmb.zst</code></pre>
      <p>
        The verifier, its tests and the receipt format are in the{' '}
        <a href={repoTree('sha256_verifier')}>repository</a>. The simulator is Google's Kickmix 1.0.0; the
        reference SHA-256 is checked against Python's <code>hashlib</code>, and so are the real Bitcoin blocks:
        each coinbase must hash to the merkle root in its header, and each header to a hash that meets its
        target. See the{' '}
        <a href={repoFile('sha256_verifier/README.md')}>verifier's README</a> for details.
      </p>
    </article>
  );
}
