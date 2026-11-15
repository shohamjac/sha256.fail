import { describe, expect, it } from 'vitest';
import { dominates, frontier, ranked, records, staircase } from './pareto';

const p = (qubits: number, cost: number) => ({ qubits, cost });

describe('dominates', () => {
  it('needs no worse on both axes and strictly better on one', () => {
    expect(dominates(p(800, 100), p(900, 200))).toBe(true);
    expect(dominates(p(800, 100), p(800, 200))).toBe(true);
    expect(dominates(p(800, 100), p(900, 100))).toBe(true);
    expect(dominates(p(800, 100), p(800, 100))).toBe(false);
    expect(dominates(p(800, 200), p(900, 100))).toBe(false);
    expect(dominates(p(900, 100), p(800, 200))).toBe(false);
  });
});

describe('frontier', () => {
  it('keeps a trade-off and drops what is dominated', () => {
    const baseline = p(831, 27088);
    const lowQubit = p(801, 50224);
    const textbook = p(1087, 45248);
    expect(frontier([textbook, baseline, lowQubit])).toEqual([lowQubit, baseline]);
  });

  it('is ordered by increasing qubits and decreasing cost', () => {
    const front = frontier([p(5, 1), p(1, 9), p(3, 4), p(4, 8), p(2, 6), p(3, 5)]);
    expect(front).toEqual([p(1, 9), p(2, 6), p(3, 4), p(5, 1)]);
    for (let i = 1; i < front.length; i++) {
      expect(front[i]!.qubits).toBeGreaterThan(front[i - 1]!.qubits);
      expect(front[i]!.cost).toBeLessThan(front[i - 1]!.cost);
    }
  });

  it('keeps every copy of an identical cost', () => {
    expect(frontier([p(2, 2), p(2, 2), p(3, 3)])).toEqual([p(2, 2), p(2, 2)]);
  });

  it('handles none and one', () => {
    expect(frontier([])).toEqual([]);
    expect(frontier([p(1, 1)])).toEqual([p(1, 1)]);
  });

  it('does not change its input', () => {
    const points = [p(3, 1), p(1, 3)];
    frontier(points);
    expect(points).toEqual([p(3, 1), p(1, 3)]);
  });
});

describe('ranked', () => {
  it('sorts by score, then by fewer qubits', () => {
    const a = { ...p(10, 10), score: 100 };
    const b = { ...p(5, 20), score: 100 };
    const c = { ...p(2, 10), score: 20 };
    expect(ranked([a, b, c])).toEqual([c, b, a]);
  });
});

describe('staircase', () => {
  it('walks down and right around the dominated region', () => {
    expect(staircase([p(1, 9), p(3, 4)], 10, 20)).toEqual([p(1, 20), p(1, 9), p(3, 9), p(3, 4), p(10, 4)]);
  });

  it('is empty for an empty frontier', () => {
    expect(staircase([], 10, 20)).toEqual([]);
  });
});

describe('records', () => {
  const e = (score: number, verifiedAt: string) => ({ score, verifiedAt });

  it('lists each time the best score improved', () => {
    const jan = e(100, '2026-01-01T00:00:00+00:00');
    const feb = e(120, '2026-02-01T00:00:00+00:00');
    const mar = e(80, '2026-03-01T00:00:00+00:00');
    const apr = e(80, '2026-04-01T00:00:00+00:00');
    expect(records([mar, apr, feb, jan]).map((r) => r.entry)).toEqual([jan, mar]);
  });

  it('takes the better of two verified at the same moment', () => {
    const a = e(100, '2026-01-01T00:00:00+00:00');
    const b = e(90, '2026-01-01T00:00:00+00:00');
    expect(records([a, b]).map((r) => r.entry)).toEqual([b]);
  });
});
