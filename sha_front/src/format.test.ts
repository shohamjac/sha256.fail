import { describe, expect, it } from 'vitest';
import { compact, count, date } from './format';

describe('format', () => {
  it('count', () => {
    expect(count(27088)).toBe('27,088');
    expect(count(831)).toBe('831');
    expect(count(27088.5)).toBe('27,088.5');
  });

  it('compact', () => {
    expect(compact(22510128)).toBe('22.5M');
    expect(compact(40229424)).toBe('40.2M');
    expect(compact(950)).toBe('950');
    expect(compact(12900)).toBe('12.9K');
    expect(compact(20000000)).toBe('20M');
    expect(compact(123456789)).toBe('123M');
  });

  it('date', () => {
    expect(date('2026-11-14T10:07:12+00:00')).toBe('14 Nov 2026');
    expect(date('not a date')).toBe('not a date');
  });
});
