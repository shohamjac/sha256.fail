/** Pareto dominance over (qubits, Toffolis); lower is better on both. */

export interface Point {
  qubits: number;
  toffoli: number;
}

/** `a` dominates `b` when it is no worse on both axes and strictly better on one. */
export function dominates(a: Point, b: Point): boolean {
  return a.qubits <= b.qubits && a.toffoli <= b.toffoli && (a.qubits < b.qubits || a.toffoli < b.toffoli);
}

/**
 * The points no other point dominates, ordered by increasing qubits (and so by
 * decreasing Toffolis). Points with identical costs are all kept.
 */
export function frontier<T extends Point>(points: readonly T[]): T[] {
  return points
    .filter((p) => !points.some((other) => dominates(other, p)))
    .sort((a, b) => a.qubits - b.qubits || a.toffoli - b.toffoli);
}

/** Ranks by score (qubits x Toffolis), best first; ties broken by fewer qubits. */
export function ranked<T extends Point & { score: number }>(points: readonly T[]): T[] {
  return [...points].sort((a, b) => a.score - b.score || a.qubits - b.qubits);
}

/**
 * The corners of the staircase bounding the dominated region, for a frontier ordered by
 * increasing qubits. Starts at the top edge above the first point and ends at the right
 * edge level with the last.
 */
export function staircase(front: readonly Point[], maxQubits: number, maxToffoli: number): Point[] {
  const corners: Point[] = [];
  front.forEach((p, i) => {
    const previous = front[i - 1];
    corners.push({ qubits: p.qubits, toffoli: previous === undefined ? maxToffoli : previous.toffoli });
    corners.push({ qubits: p.qubits, toffoli: p.toffoli });
  });
  const last = front[front.length - 1];
  if (last !== undefined) {
    corners.push({ qubits: maxQubits, toffoli: last.toffoli });
  }
  return corners;
}

export interface Improvement<T> {
  at: string;
  entry: T;
}

/**
 * Each time the best score improved, in time order: the entries that held the record.
 * `verifiedAt` is an ISO timestamp, so string order is time order.
 */
export function records<T extends { score: number; verifiedAt: string }>(entries: readonly T[]): Improvement<T>[] {
  const inTime = [...entries].sort((a, b) => a.verifiedAt.localeCompare(b.verifiedAt) || a.score - b.score);
  const out: Improvement<T>[] = [];
  let best = Infinity;
  for (const entry of inTime) {
    if (entry.score < best) {
      best = entry.score;
      out.push({ at: entry.verifiedAt, entry });
    }
  }
  return out;
}
