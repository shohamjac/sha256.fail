/**
 * The two tracks circuits are ranked on. Both pair qubits with one other cost and score
 * their product; they differ only in that cost. The circuits and their verification are the
 * same on both.
 */

import { useEffect, useState } from 'react';
import type { Entry } from './data';
import { hashParam, withHashParam } from './problems';

export type TrackId = 'toffoli' | 'depth';

export interface Track {
  id: TrackId;
  /** Name of the track, as the toggle shows it. */
  label: string;
  /** The cost, as a column heading or a label. */
  costLabel: string;
  /** The cost, mid-sentence: "no more qubits and no more ___". */
  costNoun: string;
  /** Title of the chart's vertical axis. */
  axisTitle: string;
  /** Short symbol for the cost: the score is Q times this. */
  symbol: string;
  /** What the score is, in words. */
  scoreFormula: string;
  /** Explanation of the cost, for tooltips. */
  description: string;
  /** The circuit's cost on this track; null if it was not recorded. */
  cost: (entry: Entry) => number | null;
}

export const TRACKS: Record<TrackId, Track> = {
  toffoli: {
    id: 'toffoli',
    label: 'Toffoli count',
    costLabel: 'Toffolis',
    costNoun: 'Toffolis',
    axisTitle: 'Toffolis per shot',
    symbol: 'T',
    scoreFormula: 'qubits × Toffolis',
    description: 'Mean Toffoli-like instructions executed per shot',
    cost: (entry) => entry.toffoli,
  },
  depth: {
    id: 'depth',
    label: 'Reaction depth',
    costLabel: 'Reaction depth',
    costNoun: 'reaction depth',
    axisTitle: 'Reaction depth',
    symbol: 'D',
    scoreFormula: 'qubits × reaction depth',
    description: 'Longest chain of measurement results the computer must wait for, as computed by Kickmix',
    cost: (entry) => entry.reactionDepth,
  },
};

export const DEFAULT_TRACK: TrackId = 'toffoli';

/** An entry as one track sees it: its cost on that track, and qubits times that cost. */
export interface Scored extends Entry {
  cost: number;
  score: number;
}

/** The entries that have a cost on `track`, each scored on it. */
export function scoredOn(entries: readonly Entry[], track: Track): Scored[] {
  const out: Scored[] = [];
  for (const entry of entries) {
    const cost = track.cost(entry);
    if (cost !== null) {
      out.push({ ...entry, cost, score: entry.qubits * cost });
    }
  }
  return out;
}

/** The track named in a location hash such as `#/?track=depth`; the default if none is. */
export function trackFromHash(hash: string): TrackId {
  const named = hashParam(hash, 'track');
  return named === 'depth' || named === 'toffoli' ? named : DEFAULT_TRACK;
}

/** `hash`, changed to name `track` and nothing else. */
export function hashForTrack(hash: string, track: TrackId): string {
  return withHashParam(hash, 'track', track === DEFAULT_TRACK ? null : track);
}

/**
 * The track the leaderboard page shows, kept in the URL so that a link carries it.
 * Changing it replaces the history entry rather than adding one.
 */
export function useTrack(): [TrackId, (track: TrackId) => void] {
  const [track, setTrack] = useState<TrackId>(() => trackFromHash(window.location.hash));
  useEffect(() => {
    const onHashChange = (): void => setTrack(trackFromHash(window.location.hash));
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);
  return [track, (next) => {
    window.history.replaceState(window.history.state, '', hashForTrack(window.location.hash, next));
    setTrack(next);
  }];
}
