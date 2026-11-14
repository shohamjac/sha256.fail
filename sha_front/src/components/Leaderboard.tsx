import { useEffect, useMemo, useRef, useState, type ReactElement } from 'react';
import { repoFile, repoTree } from '../config';
import type { Entry } from '../data';
import { compact, count, date } from '../format';
import { frontier, ranked } from '../pareto';

type SortKey = 'score' | 'qubits' | 'toffoli' | 'reactionDepth' | 'verifiedAt';

const COLUMNS: { key: SortKey; label: string; title: string }[] = [
  { key: 'qubits', label: 'Qubits', title: 'Highest qubit index used, plus one' },
  { key: 'toffoli', label: 'Toffolis', title: 'Mean Toffoli-like instructions executed per shot' },
  { key: 'score', label: 'Score', title: 'Qubits × Toffolis; lower is better' },
  { key: 'reactionDepth', label: 'Reaction depth', title: 'Longest chain of measurement-dependent steps, as reported by Kickmix' },
  { key: 'verifiedAt', label: 'Verified', title: 'Date of the first passing full-strength run' },
];

interface Props {
  entries: Entry[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function Leaderboard({ entries, selectedId, onSelect }: Props): ReactElement {
  const [sortKey, setSortKey] = useState<SortKey>('score');
  const [descending, setDescending] = useState(false);
  const selectedRow = useRef<HTMLTableRowElement | null>(null);

  // Rank is always by score, whatever the table is sorted by.
  const rank = useMemo(() => new Map(ranked(entries).map((e, i) => [e.id, i + 1])), [entries]);
  const frontIds = useMemo(() => new Set(frontier(entries).map((e) => e.id)), [entries]);

  const rows = useMemo(() => {
    const value = (e: Entry): number | string => e[sortKey] ?? Infinity;
    const sorted = [...entries].sort((a, b) => {
      const va = value(a);
      const vb = value(b);
      const order = va < vb ? -1 : va > vb ? 1 : 0;
      return order || rank.get(a.id)! - rank.get(b.id)!;
    });
    return descending ? sorted.reverse() : sorted;
  }, [entries, sortKey, descending, rank]);

  useEffect(() => {
    selectedRow.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [selectedId]);

  function sortBy(key: SortKey): void {
    if (key === sortKey) {
      setDescending(!descending);
    } else {
      setSortKey(key);
      setDescending(false);
    }
  }

  const selected = entries.find((e) => e.id === selectedId) ?? null;

  return (
    <div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th className="num">#</th>
              <th>Circuit</th>
              {COLUMNS.map((column) => (
                <th key={column.key} className={column.key === 'verifiedAt' ? '' : 'num'}
                  aria-sort={sortKey === column.key ? (descending ? 'descending' : 'ascending') : 'none'}>
                  <button type="button" title={column.title} onClick={() => sortBy(column.key)}>
                    {column.label}
                    {sortKey === column.key ? (descending ? ' ↓' : ' ↑') : ''}
                  </button>
                </th>
              ))}
              <th>Pareto</th>
              <th>Links</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((entry) => (
              <tr key={entry.id} ref={entry.id === selectedId ? selectedRow : null}
                className={entry.id === selectedId ? 'selected' : ''} onClick={() => onSelect(entry.id)}>
                <td className="num">{rank.get(entry.id)}</td>
                <td className="circuit">
                  <div>{entry.name}</div>
                  {entry.authors.length > 0 && <div className="authors">{entry.authors.join(', ')}</div>}
                </td>
                <td className="num">{count(entry.qubits)}</td>
                <td className="num">{count(entry.toffoli)}</td>
                <td className="num" title={count(entry.score)}>{compact(entry.score)}</td>
                <td className="num">{entry.reactionDepth === null ? '–' : count(entry.reactionDepth)}</td>
                <td>{date(entry.verifiedAt)}</td>
                <td>
                  <span className={`badge ${frontIds.has(entry.id) ? 'front' : 'dominated'}`}>
                    <span className="dot" />
                    {frontIds.has(entry.id) ? 'On the front' : 'Dominated'}
                  </span>
                </td>
                <td>
                  <span className="links" onClick={(event) => event.stopPropagation()}>
                    {entry.path !== null && <a href={repoTree(entry.path)}>files</a>}
                    <a href={repoFile(entry.receiptPath)}>receipt</a>
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selected !== null && (
        <div className="detail-panel" aria-live="polite">
          <p>
            <strong>{selected.name}.</strong> {selected.description}
          </p>
          <p>
            Passed {count(selected.directedShots)} directed and {count(selected.randomShots)} random tests.{' '}
            {selected.operations !== null && <>{count(selected.operations)} operations. </>}
            Circuit <span className="mono">{selected.id.slice(0, 16)}…</span>
          </p>
        </div>
      )}
    </div>
  );
}
