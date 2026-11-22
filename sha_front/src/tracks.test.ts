import { describe, expect, it } from 'vitest';
import { toEntries, type Receipt } from './data';
import { hashForTrack, scoredOn, trackFromHash, TRACKS } from './tracks';

function entry(id: string, qubits: number, toffoli: number, depth: number | null) {
  const sha = id.repeat(64);
  const receipt: Receipt = {
    receipt_version: 1,
    problem: 'sha256-compress-v1',
    status: 'PASS',
    circuit: { sha256: sha, file_sha256: sha, operations: 1, toffoli_static: toffoli, reaction_depth: depth },
    cost: { qubits, toffoli, score: qubits * toffoli, shots: 1048576 },
    verification: { salt: 's', directed_shots: 1179, random_shots: 1048576, full_strength: true },
    verifier: { sha_verifier_version: '0.1.0', kickmix_version: '1.0.0' },
    submission: { name: id },
    run: { started_at: '2026-11-14T10:00:00+00:00' },
  };
  return toEntries([receipt])[0]!;
}

describe('scoredOn', () => {
  it('scores qubits times the track cost', () => {
    const e = entry('a', 800, 100, 7);
    expect(scoredOn([e], TRACKS.toffoli)[0]).toMatchObject({ cost: 100, score: 80000 });
    expect(scoredOn([e], TRACKS.depth)[0]).toMatchObject({ cost: 7, score: 5600 });
  });

  it('leaves out circuits with no recorded reaction depth from that track only', () => {
    const e = entry('a', 800, 100, null);
    expect(scoredOn([e], TRACKS.depth)).toEqual([]);
    expect(scoredOn([e], TRACKS.toffoli)).toHaveLength(1);
  });

  it('does not change its input', () => {
    const e = entry('a', 800, 100, 7);
    scoredOn([e], TRACKS.depth);
    expect(e.score).toBe(80000);
  });
});

describe('the track in the URL', () => {
  it('reads it from the hash, defaulting to Toffolis', () => {
    expect(trackFromHash('#/?track=depth')).toBe('depth');
    expect(trackFromHash('#/?track=toffoli')).toBe('toffoli');
    expect(trackFromHash('#/')).toBe('toffoli');
    expect(trackFromHash('')).toBe('toffoli');
    expect(trackFromHash('#/?track=nonsense')).toBe('toffoli');
  });

  it('round-trips, with the default left out', () => {
    expect(hashForTrack('#/', 'toffoli')).toBe('#/');
    expect(hashForTrack('#/', 'depth')).toBe('#/?track=depth');
    expect(hashForTrack('#/?track=depth', 'toffoli')).toBe('#/');
    for (const id of ['toffoli', 'depth'] as const) {
      expect(trackFromHash(hashForTrack('#/', id))).toBe(id);
    }
  });

  it('keeps the problem the hash names', () => {
    expect(hashForTrack('#/?problem=sha256-compress-v1', 'depth')).toBe('#/?problem=sha256-compress-v1&track=depth');
    expect(hashForTrack('#/?problem=sha256-compress-v1&track=depth', 'toffoli')).toBe('#/?problem=sha256-compress-v1');
  });
});
