import type { ReactElement } from 'react';
import { repoFile } from '../config';

export function Rules(): ReactElement {
  return (
    <article className="prose">
      <h1>The task</h1>
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

      <h2>What it may use</h2>
      <p>
        Circuits are files in the format of Google's{' '}
        <a href="https://github.com/quantumlib/Qualtran/tree/main/kickmix">Kickmix</a> simulator. Every Kickmix
        instruction is allowed except the rotation <code>Z_POW</code>. In particular, measurement-based
        uncomputation is allowed: measuring a qubit in the X basis and correcting the phase classically.
      </p>

      <h2>How it is scored</h2>
      <ul>
        <li><strong>Qubits</strong>: the highest qubit index used, plus one. Registers and scratch all count.</li>
        <li>
          <strong>Toffolis</strong>: the mean number of <code>CCX</code>, <code>CCZ</code> and <code>CSWAP</code>{' '}
          instructions executed per shot. One under a classical condition counts only when the condition holds.
        </li>
        <li><strong>Score</strong>: qubits × Toffolis. Lower is better.</li>
      </ul>
      <p>
        The score ranks the leaderboard, but the Pareto front is the main result: a circuit with fewer qubits
        and more Toffolis than the leader is still on it.
      </p>

      <h2>Limits</h2>
      <p>
        A circuit file may be at most 512 MiB, with at most 20,000,000 operations, 65,536 qubits and 1,048,576
        classical bits. These are far above what the task needs.
      </p>
    </article>
  );
}
