import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { PROBLEM_MIN_QUBITS, PROBLEM_TITLES } from './config';
import { listed, problemsOf, toEntries, type Entry, type Receipt } from './data';
import { dominates, frontier } from './pareto';
import { scoredOn, TRACKS } from './tracks';

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
    expect(entry).toMatchObject({ name: 'Circuit bbbbbbbb', authors: [], kind: 'submission', path: null, githubUserId: null });
  });

  it('keeps a GitHub user ID only if it is a positive whole number', () => {
    const withId = (value: unknown): number | null =>
      toEntries([receipt({ submission: { name: 'x', github_user_id: value as number } })])[0]!.githubUserId;
    expect(withId(3248423)).toBe(3248423);
    for (const bad of [0, -1, 1.5, '3248423', '1/../../x', null, 2 ** 53]) {
      expect(withId(bad)).toBeNull();
    }
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

  it('records a reaction depth for every circuit', () => {
    expect(scoredOn(entries, TRACKS.depth)).toHaveLength(entries.length);
  });

  // These tests run against whatever is on the leaderboard today, and a new submission can
  // change who is on the front. So they check properties of the result, never names.
  describe.each(Object.values(TRACKS))('on the $label track', (track) => {
    const scored = scoredOn(entries, track);

    it('has a frontier that is exactly the circuits nothing dominates', () => {
      const front = frontier(scored);
      expect(front.length).toBeGreaterThanOrEqual(1);
      const ids = new Set(front.map((e) => e.id));
      for (const entry of scored) {
        const dominated = scored.some((other) => dominates(other, entry));
        expect(ids.has(entry.id)).toBe(!dominated);
      }
      for (const a of front) {
        for (const b of front) {
          expect(dominates(a, b)).toBe(false);
        }
      }
    });

    it('has the best-scoring circuit on the frontier', () => {
      const best = scored.reduce((a, b) => (b.score < a.score ? b : a));
      expect(frontier(scored).map((e) => e.id)).toContain(best.id);
    });
  });
});

describe('problemsOf', () => {
  const entriesOf = (...problems: string[]): Entry[] =>
    toEntries(problems.map((problem, i) => receipt({ problem, id: String(i % 10).repeat(64) })));

  it('puts SHA-256 compression first, so it is the view the page opens on', () => {
    expect(problemsOf(entriesOf('bitcoin-mining-v1', 'sha256-compress-v1'))).toEqual([
      'sha256-compress-v1', 'bitcoin-mining-v1']);
    expect(Object.keys(PROBLEM_TITLES)[0]).toBe('sha256-compress-v1');
  });

  it('lists the problems the site knows in the order of their titles, whatever order the receipts come in', () => {
    const known = Object.keys(PROBLEM_TITLES);
    expect(problemsOf(entriesOf(...[...known].reverse()))).toEqual(known);
    expect(problemsOf(entriesOf(...[...known].sort()))).toEqual(known);
  });

  it('puts problems it does not know after the known ones, by id', () => {
    expect(problemsOf(entriesOf('zeta-v1', 'bitcoin-mining-v1', 'alpha-v1', 'sha256-compress-v1'))).toEqual([
      'sha256-compress-v1', 'bitcoin-mining-v1', 'alpha-v1', 'zeta-v1']);
    expect(problemsOf(entriesOf('zeta-v1', 'alpha-v1'))).toEqual(['alpha-v1', 'zeta-v1']);
  });

  it('lists each problem once, and only those that have entries', () => {
    expect(problemsOf(entriesOf('sha256-compress-v1', 'sha256-compress-v1'))).toEqual(['sha256-compress-v1']);
    expect(problemsOf(entriesOf('bitcoin-mining-v1'))).toEqual(['bitcoin-mining-v1']);
    expect(problemsOf([])).toEqual([]);
  });
});

describe('the problems the site knows', () => {
  it('have a title and a qubit minimum each', () => {
    expect(Object.keys(PROBLEM_MIN_QUBITS).sort()).toEqual(Object.keys(PROBLEM_TITLES).sort());
    expect(PROBLEM_TITLES['bitcoin-mining-v1']).toBe('Bitcoin mining oracle');
    expect(PROBLEM_MIN_QUBITS['sha256-compress-v1']!.qubits).toBe(768);
    expect(PROBLEM_MIN_QUBITS['bitcoin-mining-v1']!.qubits).toBe(80);
  });
});

describe('listed', () => {
  const entry = (id: string, group: string | undefined, qubits: number, toffoli: number) =>
    toEntries([receipt({
      id: id.repeat(64),
      cost: { qubits, toffoli, score: qubits * toffoli, shots: 1048576 },
      submission: { name: id, group },
    })])[0]!;

  it('keeps only the best-scoring circuit of a group and attaches the rest', () => {
    const a = entry('a', 'work', 10, 100); // score 1000
    const b = entry('b', 'work', 20, 30); // score 600: best
    const c = entry('c', 'work', 5, 400); // score 2000
    const shown = listed([a, b, c]);
    expect(shown.map((e) => e.name)).toEqual(['b']);
    expect(shown[0]!.otherConfigurations.map((e) => e.name)).toEqual(['a', 'c']);
  });

  it('shows every ungrouped circuit and treats groups separately', () => {
    const shown = listed([entry('a', undefined, 1, 1), entry('b', undefined, 2, 2), entry('c', 'x', 3, 3),
      entry('d', 'y', 4, 4)]);
    expect(shown.map((e) => e.name).sort()).toEqual(['a', 'b', 'c', 'd']);
    expect(shown.every((e) => e.otherConfigurations.length === 0)).toBe(true);
  });

  it('breaks a tied score by fewer qubits', () => {
    const shown = listed([entry('a', 'g', 20, 10), entry('b', 'g', 10, 20)]);
    expect(shown.map((e) => e.name)).toEqual(['b']);
  });

  it('does not change its input', () => {
    const a = entry('a', 'g', 1, 1);
    const b = entry('b', 'g', 2, 2);
    listed([a, b]);
    expect(a.otherConfigurations).toEqual([]);
  });

  it('picks the best configuration on the track it is given', () => {
    const withDepth = (id: string, qubits: number, toffoli: number, depth: number) =>
      toEntries([receipt({
        id: id.repeat(64),
        circuit: { sha256: id.repeat(64), file_sha256: id.repeat(64), operations: 1, toffoli_static: 1, reaction_depth: depth },
        cost: { qubits, toffoli, score: qubits * toffoli, shots: 1048576 },
        submission: { name: id, group: 'g' },
      })])[0]!;
    const few = withDepth('a', 10, 100, 50); // Toffoli score 1,000; depth score 500.
    const shallow = withDepth('b', 10, 200, 10); // Toffoli score 2,000; depth score 100.
    expect(listed(scoredOn([few, shallow], TRACKS.toffoli)).map((e) => e.name)).toEqual(['a']);
    const onDepth = listed(scoredOn([few, shallow], TRACKS.depth));
    expect(onDepth.map((e) => e.name)).toEqual(['b']);
    expect(onDepth[0]!.otherConfigurations.map((e) => e.score)).toEqual([500]);
  });
});

describe('literature reconstructions', () => {
  const body = JSON.parse(readFileSync(new URL('../../results/index.json', import.meta.url), 'utf8')) as {
    receipts: Receipt[];
  };
  const all = scoredOn(toEntries(body.receipts), TRACKS.toffoli);
  const shown = listed(all);

  it('are verified on the same terms as every other circuit', () => {
    const literature = all.filter((e) => e.kind === 'literature');
    const names = literature.map((e) => e.name);
    expect(names).toContain('qSHA256, Toffoli-only');
    expect(names).toContain('qSHA256, measurement-based');
    for (const entry of literature) {
      expect(entry.randomShots).toBeGreaterThanOrEqual(1 << 20);
      expect(entry.path).toMatch(/^submissions\/literature-/);
    }
  });

  it('show only the best configuration of each work', () => {
    const names = shown.map((e) => e.name);
    expect(names).toContain('qSHA256, measurement-based');
    expect(names).not.toContain('qSHA256, Toffoli-only');
    const best = shown.find((e) => e.name === 'qSHA256, measurement-based')!;
    expect(best.otherConfigurations.map((e) => e.name)).toEqual(['qSHA256, Toffoli-only']);
    // Every verified circuit is either listed or named by the listed circuit of its group.
    const reachable = shown.length + shown.reduce((n, e) => n + e.otherConfigurations.length, 0);
    expect(reachable).toBe(all.length);
  });
});
