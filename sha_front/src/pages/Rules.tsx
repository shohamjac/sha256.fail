import type { ReactElement } from 'react';
import { ProblemToggle } from '../components/ProblemToggle';
import { repoFile } from '../config';
import { chosenProblem, KNOWN_PROBLEMS } from '../problems';

interface Props {
  /** The problem the visitor chose. */
  problem: string;
  onProblem: (problem: string) => void;
}

/**
 * The technical summary of each problem. What a circuit must do differs between the problems
 * and is shown for the chosen one; what it may use, the scoring and the limits are shared.
 */
export function Rules({ problem: named, onProblem }: Props): ReactElement {
  const problem = chosenProblem(named, KNOWN_PROBLEMS);
  const bitcoin = problem === 'bitcoin-mining-v1';
  return (
    <article className="prose">
      <h1>The tasks</h1>
      <ProblemToggle problems={KNOWN_PROBLEMS} value={problem} onChange={onProblem} />

      {bitcoin ? <BitcoinTask /> : <CompressionTask />}

      <h2>What it may use</h2>
      <p>
        Circuits are files in the format of Google's{' '}
        <a href="https://github.com/quantumlib/Qualtran/tree/main/kickmix">Kickmix</a> simulator. Every Kickmix
        instruction is allowed except the rotation <code>Z_POW</code>. In particular, measurement-based
        uncomputation is allowed: measuring a qubit in the X basis and correcting the phase classically.
      </p>

      <h2>How it is scored</h2>
      <ul>
        <li>
          <strong>Qubits</strong>: the highest qubit index used, plus one.{' '}
          {bitcoin
            ? 'The search register and scratch count. Classical bits do not, so the fewest possible is 80.'
            : 'Registers and scratch all count.'}
        </li>
        <li>
          <strong>Toffolis</strong>: the mean number of <code>CCX</code>, <code>CCZ</code> and <code>CSWAP</code>{' '}
          instructions executed per shot of the random tests. One under a classical condition counts only when
          the condition holds.
          {bitcoin && (
            <> The random tests use ten difficulties equally often, so a circuit that does less work at the
              easy ones is scored on its average over the ten.</>
          )}
        </li>
        <li><strong>Score</strong>: qubits × Toffolis. Lower is better.</li>
      </ul>
      <p>
        The score ranks the leaderboard, but the Pareto front is the main result: a circuit with fewer qubits
        and more Toffolis than the leader is still on it.
      </p>

      <h3>The reaction-depth track</h3>
      <p>
        A second ranking of the same circuits replaces Toffolis with <strong>reaction depth</strong>, and scores
        qubits × reaction depth. Switch between the two on the leaderboard page.
      </p>
      <p>
        A fault-tolerant computer applies Toffolis by consuming magic states, and each one leaves a random
        correction to be worked out from measurement results. Some corrections can only be worked out once
        earlier ones are known. Reaction depth is the longest chain of such steps, one after another. With
        enough magic-state factories it sets the running time, whatever the Toffoli count.
      </p>
      <p>
        The number is what Kickmix 1.0.0 computes
        (<a href="https://github.com/quantumlib/Qualtran/blob/main/kickmix/src/kickmix/circuit/circuit_util.cc"><code>compute_reaction_depth</code></a>).
        Clifford gates add nothing; each Toffoli-like gate and each <code>HMR</code> measurement adds one step;
        a gate under a classical condition waits for that condition. Kickmix treats each Toffoli as
        auto-corrected, so a chain of Toffolis that each fail to commute with the next can still have depth 2.
        Unlike the Toffoli count, it is read from the circuit as written: a conditional gate counts whether or
        not a shot runs it. The idea comes from Craig Gidney's talk <em>How to eat magic states</em> (APS March
        Meeting 2026).
      </p>

      <h2>Limits</h2>
      <p>
        A circuit file may be at most 512 MiB, with at most 20,000,000 operations, 65,536 qubits and 1,048,576
        classical bits. These are far above what either task needs.
      </p>
    </article>
  );
}

function CompressionTask(): ReactElement {
  return (
    <>
      <p className="lede">
        Build a quantum circuit that computes one SHA-256 compression: given a 512-bit block, write the 256-bit
        result of compressing it from the standard initial hash value.
      </p>
      <p>
        This page is a summary. The binding definition, with the bit order worked through and test vectors, is the{' '}
        <a href={repoFile('sha256_verifier/docs/sha256-compress-v1.md')}>contract for sha256-compress-v1</a>.
      </p>

      <h2>What the circuit must do</h2>
      <div className="table-scroll">
        <table>
          <thead>
            <tr><th>Register</th><th className="num">Qubits</th><th>At the start</th><th>At the end</th></tr>
          </thead>
          <tbody>
            <tr><td><code>block</code></td><td className="num">512</td><td>the input</td><td>unchanged</td></tr>
            <tr><td><code>digest</code></td><td className="num">256</td><td>all zero</td><td>the compression of the block</td></tr>
          </tbody>
        </table>
      </div>
      <ul>
        <li>Every other qubit is scratch: it starts at zero and must end at zero.</li>
        <li>The run must not end with its phase flipped.</li>
        <li>
          The block is arbitrary. All 512 bits are inputs and there is no padding. When the block is a padded
          message of at most 55 bytes, the digest is that message's SHA-256.
        </li>
        <li>
          The circuit is only run with <code>digest</code> and scratch at zero, so it may use the{' '}
          <code>digest</code> qubits as workspace.
        </li>
      </ul>
    </>
  );
}

/** The function of bitcoin-mining-v1, a step to a row: what the step gives, and how. */
const BITCOIN_FUNCTION: [string, string][] = [
  ['The coinbase, last block', 'inner1 = compress(midstate, extranonce ‖ tail)'],
  ['The merkle root', 'root = compress(IV, inner1 ‖ pad256)'],
  ['The header, first block', 'mid = compress(IV, version ‖ prev_hash ‖ root[0:28])'],
  ['The header, second block', 'inner2 = compress(mid, root[28:32] ‖ time ‖ bits ‖ nonce ‖ pad640)'],
  ['The block hash', 'hash = compress(IV, inner2 ‖ pad256)'],
  ['The value compared', 'masked = hash[0:20] ‖ (hash[20:32] XOR mask)'],
];

function BitcoinTask(): ReactElement {
  return (
    <>
      <p className="lede">
        Build a phase oracle for Bitcoin mining: a quantum circuit that flips the phase when a block's hash is
        below its target, and does nothing otherwise.
      </p>
      <p>
        This page is a summary. The binding definition, with the bit order worked through and test vectors, is the{' '}
        <a href={repoFile('sha256_verifier/docs/bitcoin-mining-v1.md')}>contract for bitcoin-mining-v1</a>. It is
        still a draft: until the track opens, the problem may change. What the oracle is for, and why it is
        shaped this way, is explained in <a href="#/bitcoin">Quantum Bitcoin mining</a>.
      </p>

      <h2>What the circuit must do</h2>
      <p>
        The block holds only its coinbase transaction. The circuit searches over 80 qubits: the first 6 bytes of
        the coinbase's last 64-byte block, and the header's 4-byte nonce. The rest of the block is given as
        classical bits. From these it computes five SHA-256 compressions:
      </p>
      <div className="table-scroll">
        <table>
          <thead><tr><th>Step</th><th>Computes</th></tr></thead>
          <tbody>
            {BITCOIN_FUNCTION.map(([step, formula]) => (
              <tr key={step}><td>{step}</td><td><code>{formula}</code></td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        <code>compress(state, block)</code> is one SHA-256 compression from a given state, <code>IV</code> is the
        standard initial hash value, and <code>‖</code> joins bytes. <code>pad256</code> and <code>pad640</code>{' '}
        are the constant SHA-256 padding of a 32-byte and of an 80-byte message.
      </p>
      <p>
        Read <code>masked</code> as a 256-bit number, least significant byte first, as Bitcoin reads a block
        hash. <code>bits</code> holds the target in Bitcoin's compact form, an exponent <em>e</em> and a
        mantissa <em>M</em>. The phase must be flipped exactly when the number is below{' '}
        <em>M</em> · 256<sup><em>e</em> − 3</sup>.
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr><th>Register</th><th className="num">Size</th><th>Holds</th><th>At the end</th></tr>
          </thead>
          <tbody>
            <tr>
              <td><code>extranonce</code></td><td className="num">48 qubits</td>
              <td>bytes 0–5 of the coinbase's last block</td><td>unchanged</td>
            </tr>
            <tr>
              <td><code>nonce</code></td><td className="num">32 qubits</td>
              <td>header bytes 76–79</td><td>unchanged</td>
            </tr>
            <tr>
              <td><code>midstate</code></td><td className="num">256 bits</td>
              <td>the SHA-256 state before the coinbase's last block</td><td>any state</td>
            </tr>
            <tr>
              <td><code>tail</code></td><td className="num">464 bits</td>
              <td>bytes 6–63 of the coinbase's last block</td><td>any state</td>
            </tr>
            <tr>
              <td><code>version</code></td><td className="num">32 bits</td>
              <td>header bytes 0–3</td><td>any state</td>
            </tr>
            <tr>
              <td><code>prev_hash</code></td><td className="num">256 bits</td>
              <td>header bytes 4–35</td><td>any state</td>
            </tr>
            <tr>
              <td><code>time</code></td><td className="num">32 bits</td>
              <td>header bytes 68–71</td><td>any state</td>
            </tr>
            <tr>
              <td><code>bits</code></td><td className="num">32 bits</td>
              <td>header bytes 72–75: hashed, and read as the target</td><td>any state</td>
            </tr>
            <tr>
              <td><code>mask</code></td><td className="num">96 bits</td>
              <td>XORed into the last three words of the block hash</td><td>any state</td>
            </tr>
          </tbody>
        </table>
      </div>
      <ul>
        <li>
          Every other qubit is scratch: it starts at zero and must end at zero. There is no output register:
          the phase is the only result.
        </li>
        <li>
          The seven classical registers are bits, not qubits. The circuit reads them through classical
          conditions, may overwrite them, and may leave them in any state.
        </li>
        <li>
          With a mask of zero the oracle is Bitcoin's own check, except that Bitcoin also accepts a hash equal
          to the target.
        </li>
        <li>
          <code>bits</code> always holds an exponent from <code>0x17</code> to <code>0x20</code> and a mantissa
          from 1 to <code>0x7fffff</code>, and <code>tail</code> is always the end of a padded message. What the
          circuit does on other inputs is not tested.
        </li>
      </ul>
    </>
  );
}
