import { useState, type ReactElement } from 'react';
import { Leaderboard } from '../components/Leaderboard';
import { ParetoChart } from '../components/ParetoChart';
import { Records } from '../components/Records';
import { StatTiles } from '../components/StatTiles';
import { PROBLEM_TITLES } from '../config';
import { problemsOf, type Entry } from '../data';

export function Home({ entries }: { entries: Entry[] }): ReactElement {
  const problems = problemsOf(entries);
  const [problem, setProblem] = useState(problems[0] ?? '');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const shown = entries.filter((e) => e.problem === problem);
  const unlisted = shown.reduce((n, e) => n + e.otherConfigurations.length, 0);

  return (
    <>
      <div className="intro">
        <h1>How cheaply can a quantum computer run SHA-256?</h1>
        <p>
          An open benchmark for quantum circuits that compute the SHA-256 compression function. Every circuit
          here was simulated on more than a million random inputs and got every one right. Two numbers are
          scored: how many qubits it needs, and how many Toffoli gates it runs.
        </p>
      </div>

      {problems.length > 1 && (
        <div className="filters">
          <label htmlFor="problem">Problem</label>
          <select id="problem" value={problem} onChange={(event) => { setProblem(event.target.value); setSelectedId(null); }}>
            {problems.map((p) => <option key={p} value={p}>{PROBLEM_TITLES[p] ?? p}</option>)}
          </select>
        </div>
      )}

      {shown.length === 0 ? (
        <p className="notice">No circuit has passed verification yet.</p>
      ) : (
        <>
          <StatTiles entries={shown} />

          <section className="section">
            <h2>Pareto front</h2>
            <p className="lede">
              Each mark is a verified circuit. Left is fewer qubits, down is fewer Toffolis. A circuit is on the
              front when no other circuit is at least as good on both.
            </p>
            <div className="card">
              <ParetoChart entries={shown} selectedId={selectedId} onSelect={setSelectedId} />
            </div>
          </section>

          <section className="section">
            <h2>Leaderboard</h2>
            <p className="lede">
              Ranked by score, the product of qubits and Toffolis. Select a row for details; every entry links to
              its circuit files and to the receipt of its verification run.
              {unlisted > 0 && (
                <>
                  {' '}Where one work has several verified configurations, only its best-scoring one is listed;{' '}
                  {unlisted === 1 ? '1 other is' : `${unlisted} others are`} named in that row's details.
                </>
              )}
            </p>
            <div className="card">
              <Leaderboard entries={shown} selectedId={selectedId} onSelect={setSelectedId} />
            </div>
          </section>

          <section className="section">
            <h2>Record history</h2>
            <p className="lede">Each circuit that set a new best score, newest first.</p>
            <div className="card">
              <Records entries={shown} />
            </div>
          </section>
        </>
      )}
    </>
  );
}
