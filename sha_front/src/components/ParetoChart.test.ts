import { describe, expect, it } from 'vitest';
import { axisTicks } from './ParetoChart';

describe('axisTicks', () => {
  it('spaces a narrow range evenly', () => {
    expect(axisTicks(715, 1217, 7)).toEqual([800, 900, 1000, 1100, 1200]);
  });

  it('labels both ends of a wide range', () => {
    expect(axisTicks(21670, 112860, 6)).toEqual([30000, 40000, 50000, 60000, 80000, 100000]);
  });

  it('thins out across several decades', () => {
    expect(axisTicks(150, 90000, 6)).toEqual([200, 500, 1000, 2000, 5000, 10000, 20000, 50000]);
    expect(axisTicks(15, 9000000, 6)).toEqual([100, 1000, 10000, 100000, 1000000]);
  });

  it('stays inside the range', () => {
    for (const [low, high] of [[715, 1217], [21670, 112860], [3, 4000]] as const) {
      for (const tick of axisTicks(low, high, 6)) {
        expect(tick).toBeGreaterThanOrEqual(low);
        expect(tick).toBeLessThanOrEqual(high);
      }
    }
  });
});
