import { useMemo, useState, type ReactElement } from 'react';
import { Leaderboard } from '../components/Leaderboard';
import { ParetoChart } from '../components/ParetoChart';
import { Records } from '../components/Records';
import { StatTiles } from '../components/StatTiles';
import { SubmissionDialog } from '../components/SubmissionDialog';
import { PROBLEM_MIN_QUBITS, PROBLEM_TITLES } from '../config';
import { listed, problemsOf, type Entry } from '../data';
import { scoredOn, TRACKS, useTrack, type TrackId } from '../tracks';

export function Home({ entries }: { entries: Entry[] }): ReactElement {
  const problems = problemsOf(entries);
  const [problem, setProblem] = useState(problems[0] ?? '');
  const [trackId, setTrackId] = useTrack();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const track = TRACKS[trackId];
  const minQubits = PROBLEM_MIN_QUBITS[problem];
  const shown = useMemo(
    () => listed(scoredOn(entries.filter((e) => e.problem === problem), track)),
    [entries, problem, track],
  );
  const unlisted = shown.reduce((n, e) => n + e.otherConfigurations.length, 0);

  return (
    <>
      <div className="intro">
        <h1>How cheaply can a quantum computer run SHA-256?</h1>
        <p>
          An open benchmark for quantum circuits that compute the SHA-256 compression function. Every circuit
          here was simulated on more than a million random inputs and got every one right. Circuits are ranked on
          two tracks. Both count the qubits a circuit needs. The Toffoli track also counts how many Toffoli gates
          it runs; the reaction-depth track counts the longest chain of measurements a fault-tolerant computer must
          wait for, one after another, while running it.
        </p>
      </div>

      <div className="filters">
        <span className="filter-label" id="track-label">Rank by</span>
        <div className="segmented" role="group" aria-labelledby="track-label">
          {(Object.keys(TRACKS) as TrackId[]).map((id) => (
            <button key={id} type="button" aria-pressed={id === trackId} title={TRACKS[id].description}
              onClick={() => setTrackId(id)}>
              {TRACKS[id].label}
            </button>
          ))}
        </div>
        {problems.length > 1 && (
          <>
            <label htmlFor="problem">Problem</label>
            <select id="problem" value={problem} onChange={(event) => { setProblem(event.target.value); setSelectedId(null); }}>
              {problems.map((p) => <option key={p} value={p}>{PROBLEM_TITLES[p] ?? p}</option>)}
            </select>
          </>
        )}
      </div>

      <SubmissionDialog entry={shown.find((e) => e.id === openId) ?? null} entries={shown} track={track}
        onClose={() => setOpenId(null)} />

      {shown.length === 0 ? (
        <p className="notice">No circuit has passed verification yet.</p>
      ) : (
        <>
          <StatTiles entries={shown} track={track} />

          <section className="section">
            <h2>Pareto front</h2>
            <p className="lede">
              Each mark is a verified circuit. Left is fewer qubits, down is {trackId === 'toffoli'
                ? 'fewer Toffolis'
                : 'less reaction depth'}. A circuit is on the front when no other circuit is at least as good on both.
              {minQubits !== undefined && (
                <> The dashed line is the fewest qubits a circuit can have: {minQubits.what}.</>
              )}
            </p>
            <div className="card">
              <ParetoChart entries={shown} track={track} selectedId={selectedId} onSelect={setSelectedId}
                minQubits={minQubits?.qubits} />
            </div>
          </section>

          <section className="section">
            <h2>Leaderboard</h2>
            <p className="lede">
              Ranked by score, the product of qubits and {track.costNoun}. Select a row to see a
              circuit's parameters and notes; every entry links to its circuit files and to the receipt of its
              verification run.
              {unlisted > 0 && (
                <>
                  {' '}Where one work has several verified configurations, only its best-scoring one is listed;{' '}
                  {unlisted === 1 ? '1 other is' : `${unlisted} others are`} named in that circuit's details.
                </>
              )}
            </p>
            <div className="card">
              <Leaderboard entries={shown} track={track} selectedId={selectedId}
                onOpen={(id) => { setSelectedId(id); setOpenId(id); }} />
            </div>
          </section>

          <section className="section">
            <h2>Record history</h2>
            <p className="lede">Each circuit that set a new best score on the {track.label.toLowerCase()} track, newest first.</p>
            <div className="card">
              <Records entries={shown} />
            </div>
          </section>
        </>
      )}
    </>
  );
}
