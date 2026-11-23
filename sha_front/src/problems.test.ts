import { describe, expect, it } from 'vitest';
import {
  chosenProblem, DEFAULT_PROBLEM, hashForProblem, hashParam, KNOWN_PROBLEMS, problemFromHash, withHashParam,
} from './problems';

describe('choices in the location hash', () => {
  it('reads a value from the query after the page', () => {
    expect(hashParam('#/rules?problem=x', 'problem')).toBe('x');
    expect(hashParam('#/?track=depth&problem=x', 'problem')).toBe('x');
    expect(hashParam('#/rules', 'problem')).toBeNull();
    expect(hashParam('', 'problem')).toBeNull();
  });

  it('sets and removes one value, keeping the page and the other values', () => {
    expect(withHashParam('#/rules', 'problem', 'x')).toBe('#/rules?problem=x');
    expect(withHashParam('#/?track=depth', 'problem', 'x')).toBe('#/?track=depth&problem=x');
    expect(withHashParam('#/?track=depth&problem=x', 'problem', 'y')).toBe('#/?track=depth&problem=y');
    expect(withHashParam('#/?track=depth&problem=x', 'problem', null)).toBe('#/?track=depth');
    expect(withHashParam('#/rules?problem=x', 'problem', null)).toBe('#/rules');
    expect(withHashParam('', 'problem', 'x')).toBe('#/?problem=x');
  });
});

describe('the problem in the URL', () => {
  it('opens on the Bitcoin mining oracle', () => {
    expect(DEFAULT_PROBLEM).toBe('bitcoin-mining-v1');
    expect(problemFromHash('#/')).toBe('bitcoin-mining-v1');
    expect(problemFromHash('')).toBe('bitcoin-mining-v1');
    expect(problemFromHash('#/?track=depth')).toBe('bitcoin-mining-v1');
  });

  it('reads the problem a link names', () => {
    expect(problemFromHash('#/?problem=sha256-compress-v1')).toBe('sha256-compress-v1');
    expect(problemFromHash('#/rules?problem=sha256-compress-v1')).toBe('sha256-compress-v1');
  });

  it('round-trips on every page, with the default left out', () => {
    expect(hashForProblem('#/', DEFAULT_PROBLEM)).toBe('#/');
    expect(hashForProblem('#/rules', 'sha256-compress-v1')).toBe('#/rules?problem=sha256-compress-v1');
    expect(hashForProblem('#/rules?problem=sha256-compress-v1', DEFAULT_PROBLEM)).toBe('#/rules');
    for (const page of ['#/', '#/rules', '#/?track=depth']) {
      for (const problem of KNOWN_PROBLEMS) {
        expect(problemFromHash(hashForProblem(page, problem))).toBe(problem);
      }
    }
  });

  it('keeps the track the hash names', () => {
    expect(hashForProblem('#/?track=depth', 'sha256-compress-v1')).toBe('#/?track=depth&problem=sha256-compress-v1');
  });
});

describe('chosenProblem', () => {
  it('shows the named problem when the page has it', () => {
    expect(chosenProblem('sha256-compress-v1', KNOWN_PROBLEMS)).toBe('sha256-compress-v1');
    expect(chosenProblem('bitcoin-mining-v1', KNOWN_PROBLEMS)).toBe('bitcoin-mining-v1');
  });

  it('falls back to the first problem the page has', () => {
    // The Bitcoin problem is the default, but has no circuits until its first receipt.
    expect(chosenProblem('bitcoin-mining-v1', ['sha256-compress-v1'])).toBe('sha256-compress-v1');
    expect(chosenProblem('no-such-problem', KNOWN_PROBLEMS)).toBe('bitcoin-mining-v1');
    expect(chosenProblem('bitcoin-mining-v1', [])).toBe('');
  });
});
