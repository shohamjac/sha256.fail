import type { ReactElement } from 'react';
import { compact, count } from '../format';
import { frontier } from '../pareto';
import type { Scored, Track } from '../tracks';

function least(entries: Scored[], key: 'score' | 'qubits' | 'cost'): Scored {
  return entries.reduce((best, e) => (e[key] < best[key] ? e : best));
}

export function StatTiles({ entries, track }: { entries: Scored[]; track: Track }): ReactElement {
  const bestScore = least(entries, 'score');
  const fewestQubits = least(entries, 'qubits');
  const leastCost = least(entries, 'cost');
  const onFront = frontier(entries).length;
  const tiles = [
    { label: 'Best score', value: compact(bestScore.score), detail: bestScore.name },
    { label: 'Fewest qubits', value: count(fewestQubits.qubits), detail: fewestQubits.name },
    {
      label: track.id === 'toffoli' ? 'Fewest Toffolis' : 'Lowest reaction depth',
      value: count(leastCost.cost),
      detail: leastCost.name,
    },
    { label: 'Verified circuits', value: count(entries.length), detail: `${onFront} on the Pareto front` },
  ];
  return (
    <div className="tiles">
      {tiles.map((tile) => (
        <div className="tile" key={tile.label}>
          <div className="label">{tile.label}</div>
          <div className="value">{tile.value}</div>
          <div className="detail" title={tile.detail}>{tile.detail}</div>
        </div>
      ))}
    </div>
  );
}
