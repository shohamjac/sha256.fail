import type { ReactElement } from 'react';
import type { Entry } from '../data';
import { compact, count, date } from '../format';
import { records } from '../pareto';

/** The history of the best score: every circuit that set a new record, newest first. */
export function Records({ entries }: { entries: Entry[] }): ReactElement {
  const history = records(entries).reverse();
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Circuit</th>
            <th className="num">Score</th>
            <th className="num">Improvement</th>
          </tr>
        </thead>
        <tbody>
          {history.map((record, i) => {
            const previous = history[i + 1];
            const gain = previous === undefined ? null : 1 - record.entry.score / previous.entry.score;
            return (
              <tr key={record.entry.id} style={{ cursor: 'default' }}>
                <td>{date(record.at)}</td>
                <td>{record.entry.name}</td>
                <td className="num" title={count(record.entry.score)}>{compact(record.entry.score)}</td>
                <td className="num">{gain === null ? 'first record' : `−${(100 * gain).toFixed(1)}%`}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
