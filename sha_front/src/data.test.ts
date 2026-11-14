import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { problemsOf, toEntries, type Receipt } from './data';
import { frontier } from './pareto';

function receipt(overrides: Partial<Receipt> & { id?: string } = {}): Receipt {
  const { id = 'a'.repeat(64), ...rest } = overrides;
  return {
    receipt_version: 1,
    problem: 'sha256-compress-v1',
    status: 'PASS',
    circuit: { sha256: id, file_sha256: id, operations: 10, toffoli_static: 5, reaction_depth: 3 },
    cost: { qubits: 800, toffoli: 100, score: 80000, shots: 1048576 },
    verification: { salt: 's', directed_shots: 1179, random_shots: 1048576, full_strength: true },
    verifier: { sha_verifier_version: '0.1.0', kickmix_version: '1.0.0' },
    submission: { name: 'Test', authors: ['someone'], kind: 'submission', description: 'd', path: 'submissions/test' },
    run: { started_at: '2026-11-14T10:00:00+00:00' },
    ...rest,
  };
}

describe('toEntries', () => {
  it('maps a passing full-strength receipt', () => {
    const [entry, ...others] = toEntries([receipt()]);
    expect(others).toEqual([]);
    expect(entry).toMatchObject({
      id: 'a'.repeat(64), name: 'Test', authors: ['someone'], kind: 'submission', qubits: 800, toffoli: 100,
      score: 80000, path: 'submissions/test', randomShots: 1048576, directedShots: 1179,
      receiptPath: `results/sha256-compress-v1/${'a'.repeat(64)}.json`,
    });
  });

  it('leaves out failures and development runs', () => {
    const failed = receipt({ status: 'FAIL', cost: null });
    const partial = receipt({
      verification: { salt: '', directed_shots: 1179, random_shots: 4096, full_strength: false },
    });
    expect(toEntries([failed, partial])).toEqual([]);
  });

  it('keeps the earliest passing run of the same circuit', () => {
    const later = receipt({ run: { started_at: '2026-12-01T00:00:00+00:00' } });
    const earlier = receipt({ run: { started_at: '2026-11-01T00:00:00+00:00' } });
    const entries = toEntries([later, earlier]);
    expect(entries).toHaveLength(1);
    expect(entries[0]!.verifiedAt).toBe('2026-11-01T00:00:00+00:00');
  });

  it('copes with missing metadata', () => {
    const [entry] = toEntries([receipt({ submission: null, id: 'b'.repeat(64) })]);
    expect(entry).toMatchObject({ name: 'Circuit bbbbbbbb', authors: [], kind: 'submission', path: null });
  });

  it('treats an unknown kind as a submission', () => {
    const [entry] = toEntries([receipt({ submission: { name: 'x', kind: 'something-else' } })]);
    expect(entry!.kind).toBe('submission');
  });
});

describe('the repository results', () => {
  const body = JSON.parse(readFileSync(new URL('../../results/index.json', import.meta.url), 'utf8')) as {
    receipts: Receipt[];
  };
  const entries = toEntries(body.receipts);

  it('has the baseline and its variants', () => {
    expect(entries.length).toBeGreaterThanOrEqual(3);
    expect(problemsOf(entries)).toContain('sha256-compress-v1');
    for (const entry of entries) {
      expect(entry.score).toBeCloseTo(entry.qubits * entry.toffoli, 6);
      expect(entry.randomShots).toBeGreaterThanOrEqual(1 << 20);
      expect(entry.path).toMatch(/^submissions\//);
    }
  });

  it('puts the baseline on the frontier and the textbook variant off it', () => {
    const names = frontier(entries).map((e) => e.name);
    expect(names).toContain('Baseline');
    expect(names).toContain('Low-qubit adder');
    expect(names).not.toContain('Compute, copy, uncompute');
  });
});
