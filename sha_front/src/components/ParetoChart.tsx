import { ticks } from 'd3-array';
import { scaleLog } from 'd3-scale';
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent, type ReactElement } from 'react';
import type { Kind } from '../data';
import { compact, count, date } from '../format';
import { dominates, frontier, staircase } from '../pareto';
import type { Scored, Track } from '../tracks';

const MARGIN = { top: 14, right: 20, bottom: 46, left: 58 };
const MARK = 5; // Half-size of a mark, in pixels.
const HIT = 36; // A pointer this close to a mark selects it.
const MAX_LABELS = 4;

const KIND_LABEL: Record<Kind, string> = {
  submission: 'Submission',
  baseline: 'Reference construction',
  literature: 'From the literature',
};

function Shape({ kind, x, y, r, className }: { kind: Kind; x: number; y: number; r: number; className: string }) {
  if (kind === 'baseline') {
    return <rect className={className} x={x - r} y={y - r} width={2 * r} height={2 * r} rx={1} />;
  }
  if (kind === 'literature') {
    const d = r * 1.3;
    return <path className={className} d={`M${x},${y - d} L${x + d},${y} L${x},${y + d} L${x - d},${y} Z`} />;
  }
  return <circle className={className} cx={x} cy={y} r={r} />;
}

/**
 * Round tick values inside [low, high] for a log axis. A narrow range gets evenly spaced
 * values; a wide one gets 1-2-3-4-5-6-8 steps per decade (or 1-2-5 if those are too many),
 * so the compressed upper end is not over-labelled and the lower end is not left bare.
 */
export function axisTicks(low: number, high: number, target: number): number[] {
  if (high / low < 2.5) {
    return ticks(low, high, target).filter((t) => t >= low && t <= high);
  }
  for (const steps of [[1, 2, 3, 4, 5, 6, 8], [1, 2, 5], [1]]) {
    const values: number[] = [];
    for (let decade = 10 ** Math.floor(Math.log10(low)); decade <= high; decade *= 10) {
      values.push(...steps.map((step) => step * decade).filter((v) => v >= low && v <= high));
    }
    if (values.length <= target + 2) {
      return values;
    }
  }
  return [];
}

function padded(values: number[], factor: number): [number, number] {
  return [Math.min(...values) / factor, Math.max(...values) * factor];
}

function useWidth(): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(900);
  useEffect(() => {
    const element = ref.current;
    if (element === null) {
      return;
    }
    setWidth(element.clientWidth);
    const observer = new ResizeObserver(() => setWidth(element.clientWidth));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

interface Props {
  entries: Scored[];
  /** The track whose cost is on the vertical axis. */
  track: Track;
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** The fewest qubits any circuit for this problem can have, drawn as a vertical line. */
  minQubits?: number;
}

export function ParetoChart({ entries, track, selectedId, onSelect, minQubits }: Props): ReactElement {
  const [ref, width] = useWidth();
  const [hoverId, setHoverId] = useState<string | null>(null);

  const height = Math.round(Math.min(460, Math.max(300, width * 0.52)));
  const plot = {
    left: MARGIN.left,
    right: width - MARGIN.right,
    top: MARGIN.top,
    bottom: height - MARGIN.bottom,
  };

  const model = useMemo(() => {
    const front = frontier(entries);
    const frontIds = new Set(front.map((e) => e.id));
    // The qubit axis always reaches down to the limit, however far the circuits are from it.
    const [qMin, qMax] = padded([...entries.map((e) => e.qubits), ...(minQubits === undefined ? [] : [minQubits])], 1.12);
    const [tMin, tMax] = padded(entries.map((e) => e.cost), 1.25);
    const bestScore = Math.min(...entries.map((e) => e.score));
    return { front, frontIds, qMin, qMax, tMin, tMax, bestScore };
  }, [entries, minQubits]);

  const x = scaleLog().domain([model.qMin, model.qMax]).range([plot.left, plot.right]);
  const y = scaleLog().domain([model.tMin, model.tMax]).range([plot.bottom, plot.top]);
  const xTicks = axisTicks(model.qMin, model.qMax, width < 520 ? 4 : 7);
  const yTicks = axisTicks(model.tMin, model.tMax, 6);
  const compactY = model.tMax >= 10000;

  // The staircase and the region it bounds (everything some frontier circuit dominates).
  const corners = staircase(model.front, model.qMax, model.tMax);
  const stairs = corners.map((c, i) => `${i === 0 ? 'M' : 'L'}${x(c.qubits)},${y(c.cost)}`).join(' ');
  const region = corners.length > 0 ? `${stairs} L${plot.right},${plot.top} Z` : '';

  // Lines of equal score: straight on log-log axes. The best score, and twice it.
  const isoLines = [1, 2]
    .map((multiple) => {
      const score = model.bestScore * multiple;
      const q0 = Math.max(model.qMin, score / model.tMax);
      const q1 = Math.min(model.qMax, score / model.tMin);
      return { score, multiple, q0, q1 };
    })
    .filter((line) => line.q0 < line.q1);

  // Direct labels on the frontier only, and only a few: the table carries the rest.
  const labelled = new Set(
    [...model.front].sort((a, b) => a.score - b.score).slice(0, MAX_LABELS).map((e) => e.id),
  );

  const activeId = hoverId ?? selectedId;
  const active = entries.find((e) => e.id === activeId) ?? null;
  const kinds = [...new Set(entries.map((e) => e.kind))];
  // With a single kind on the chart the legend swatches take its shape; with several,
  // they stay round and the shapes get their own legend entries.
  const swatchKind: Kind = kinds.length === 1 ? kinds[0]! : 'submission';

  function nearest(event: MouseEvent<SVGSVGElement>): Scored | null {
    const box = event.currentTarget.getBoundingClientRect();
    const px = event.clientX - box.left;
    const py = event.clientY - box.top;
    let best: Scored | null = null;
    let bestDistance = HIT;
    for (const entry of entries) {
      const distance = Math.hypot(x(entry.qubits) - px, y(entry.cost) - py);
      if (distance < bestDistance) {
        best = entry;
        bestDistance = distance;
      }
    }
    return best;
  }

  function onKey(event: KeyboardEvent<SVGGElement>, id: string): void {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onSelect(id);
    }
  }

  // Dominated marks first, so frontier marks sit on top where they overlap.
  const drawOrder = [...entries].sort(
    (a, b) => Number(model.frontIds.has(a.id)) - Number(model.frontIds.has(b.id)),
  );

  return (
    <div>
      <div className="legend" aria-hidden="true">
        <span>
          <svg width="12" height="12" style={{ fill: 'var(--series-1)' }}><Shape kind={swatchKind} x={6} y={6} r={4.5} className="" /></svg>
          On the Pareto front
        </span>
        <span>
          <svg width="12" height="12" style={{ fill: 'var(--deemphasis)' }}><Shape kind={swatchKind} x={6} y={6} r={4.5} className="" /></svg>
          Dominated
        </span>
        <span>
          <svg width="22" height="12"><line x1="1" y1="6" x2="21" y2="6" stroke="var(--series-1)" strokeWidth="2" strokeLinecap="round" /></svg>
          Frontier
        </span>
        <span>
          <svg width="22" height="12"><line x1="1" y1="6" x2="21" y2="6" stroke="var(--axis)" strokeWidth="1" /></svg>
          Equal score ({track.scoreFormula})
        </span>
        {kinds.length > 1 &&
          kinds.map((kind) => (
            <span key={kind}>
              <svg width="12" height="12" style={{ fill: 'var(--text-muted)' }}><Shape kind={kind} x={6} y={6} r={4} className="" /></svg>
              {KIND_LABEL[kind]}
            </span>
          ))}
      </div>

      <div className="chart" ref={ref}>
        <svg
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="group"
          aria-label={`Qubits against ${track.costNoun} for every verified circuit. `
            + (minQubits === undefined ? '' : `No circuit can have fewer than ${count(minQubits)} qubits. `)
            + 'The leaderboard below lists the same data.'}
          onPointerMove={(event) => setHoverId(nearest(event)?.id ?? null)}
          onPointerLeave={() => setHoverId(null)}
          onClick={(event) => {
            const hit = nearest(event);
            if (hit !== null) {
              onSelect(hit.id);
            }
          }}
        >
          <defs>
            <clipPath id="plot-area">
              <rect x={plot.left} y={plot.top} width={plot.right - plot.left} height={plot.bottom - plot.top} />
            </clipPath>
          </defs>

          <g className="grid">
            {xTicks.map((t) => <line key={`x${t}`} x1={x(t)} x2={x(t)} y1={plot.top} y2={plot.bottom} />)}
            {yTicks.map((t) => <line key={`y${t}`} x1={plot.left} x2={plot.right} y1={y(t)} y2={y(t)} />)}
          </g>

          <g clipPath="url(#plot-area)">
            {region !== '' && <path className="front-area" d={region} />}
            {isoLines.map((line) => (
              <line key={line.multiple} className="iso"
                x1={x(line.q0)} y1={y(line.score / line.q0)} x2={x(line.q1)} y2={y(line.score / line.q1)} />
            ))}
            {minQubits !== undefined && (
              <line className="limit" x1={x(minQubits)} x2={x(minQubits)} y1={plot.top} y2={plot.bottom} />
            )}
            {stairs !== '' && <path className="front-line" d={stairs} />}
          </g>

          <rect className="frame" x={plot.left} y={plot.top} width={plot.right - plot.left} height={plot.bottom - plot.top} />

          {isoLines.map((line) => {
            // The line falls to the right. Text hung under its right end, or sat on its left
            // end, therefore never crosses it; use whichever end leaves room inside the frame.
            const rightY = y(line.score / line.q1) + 15;
            const underRight = rightY < plot.bottom - 6;
            return (
              <text key={line.multiple} className="iso-label" textAnchor={underRight ? 'end' : 'start'}
                x={underRight ? x(line.q1) - 6 : x(line.q0) + 6}
                y={underRight ? rightY : y(line.score / line.q0) - 7}>
                {width < 520
                  ? (line.multiple === 1 ? compact(line.score) : `${line.multiple}×`)
                  : (line.multiple === 1 ? `best score ${compact(line.score)}` : `${line.multiple}× best score`)}
              </text>
            );
          })}

          {minQubits !== undefined && (
            // Runs up the left side of the line, where no mark can be.
            <text className="limit-label" textAnchor="end"
              transform={`translate(${x(minQubits) - 6} ${plot.top + 8}) rotate(-90)`}>
              {width < 520 ? `min. ${count(minQubits)} qubits` : `minimum: ${count(minQubits)} qubits`}
            </text>
          )}

          {xTicks.map((t) => (
            <text key={t} className="tick" x={x(t)} y={plot.bottom + 18} textAnchor="middle">{count(t)}</text>
          ))}
          {yTicks.map((t) => (
            <text key={t} className="tick" x={plot.left - 8} y={y(t) + 4} textAnchor="end">
              {compactY ? compact(t) : count(t)}
            </text>
          ))}
          <text className="axis-title" x={(plot.left + plot.right) / 2} y={height - 6} textAnchor="middle">
            Qubits
          </text>
          <text className="axis-title" textAnchor="middle"
            transform={`translate(14 ${(plot.top + plot.bottom) / 2}) rotate(-90)`}>
            {track.axisTitle}
          </text>

          {drawOrder.map((entry) => {
            const onFront = model.frontIds.has(entry.id);
            const cx = x(entry.qubits);
            const cy = y(entry.cost);
            const flip = cx > plot.right - 150;
            return (
              <g
                key={entry.id}
                className={`mark ${onFront ? 'front' : 'dominated'} ${entry.id === activeId ? 'active' : ''}`}
                tabIndex={0}
                role="button"
                aria-label={`${entry.name}: ${count(entry.qubits)} qubits, ${count(entry.cost)} ${track.costNoun}, ${
                  onFront ? 'on the Pareto front' : 'dominated'
                }`}
                onFocus={() => setHoverId(entry.id)}
                onBlur={() => setHoverId(null)}
                onKeyDown={(event) => onKey(event, entry.id)}
              >
                <circle className="halo" cx={cx} cy={cy} r={MARK + 5} />
                <Shape kind={entry.kind} x={cx} y={cy} r={MARK} className="shape" />
                {labelled.has(entry.id) && (
                  <text className="point-label" x={cx + (flip ? -11 : 11)} y={cy - 9}
                    textAnchor={flip ? 'end' : 'start'}>
                    {entry.name}
                  </text>
                )}
              </g>
            );
          })}
        </svg>

        {active !== null && hoverId !== null && (
          <Tooltip
            entry={active}
            track={track}
            onFront={model.frontIds.has(active.id)}
            dominatedBy={entries.filter((other) => dominates(other, active)).length}
            left={x(active.qubits)}
            top={y(active.cost)}
            width={width}
          />
        )}
      </div>
    </div>
  );
}

function Tooltip({ entry, track, onFront, dominatedBy, left, top, width }: {
  entry: Scored;
  track: Track;
  onFront: boolean;
  dominatedBy: number;
  left: number;
  top: number;
  width: number;
}): ReactElement {
  // Sit beside the mark, on whichever side has room; never cover the mark itself.
  const toLeft = left > width / 2;
  const style = {
    top: Math.max(0, top - 18),
    ...(toLeft ? { right: width - left + 16 } : { left: left + 16 }),
  };
  return (
    <div className="tooltip" style={style} role="status">
      <div className="head">
        <div className="name">{entry.name}</div>
        {entry.authors.length > 0 && <div className="authors">by {entry.authors.join(', ')}</div>}
      </div>
      <dl>
        <dt>Qubits</dt>
        <dd>{count(entry.qubits)}</dd>
        <dt>{track.costLabel}</dt>
        <dd>{count(entry.cost)}</dd>
        <dt>Score</dt>
        <dd>{compact(entry.score)}</dd>
      </dl>
      <div className="status">
        {entry.kind !== 'submission' && <>{KIND_LABEL[entry.kind]} · </>}
        {onFront
          ? 'On the Pareto front'
          : `Dominated by ${dominatedBy} circuit${dominatedBy === 1 ? '' : 's'}`}
        {' · '}
        {date(entry.verifiedAt)}
      </div>
    </div>
  );
}
