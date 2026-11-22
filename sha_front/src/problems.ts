/**
 * Which problem the visitor is looking at, and how the location hash carries it.
 *
 * A page's choices live in a query after the page, as in `#/rules?problem=sha256-compress-v1`,
 * so that a link carries them. The problem is one such choice and the track is another (see
 * tracks.ts); each is left out of the hash when it is the default.
 */

import { useEffect, useState } from 'react';
import { PROBLEM_TITLES } from './config';

/** The value the hash's query gives `name`, or null if it gives none. */
export function hashParam(hash: string, name: string): string | null {
  return new URLSearchParams(hash.split('?')[1] ?? '').get(name);
}

/** `hash` with `name` set to `value` in its query, or removed when `value` is null. */
export function withHashParam(hash: string, name: string, value: string | null): string {
  const [page, query = ''] = hash.split('?');
  const params = new URLSearchParams(query);
  if (value === null) {
    params.delete(name);
  } else {
    params.set(name, value);
  }
  const rest = params.toString();
  return (page || '#/') + (rest === '' ? '' : `?${rest}`);
}

/** The problems the site knows, in the order it offers them. */
export const KNOWN_PROBLEMS: readonly string[] = Object.keys(PROBLEM_TITLES);

/** The problem shown when the hash names none. */
export const DEFAULT_PROBLEM: string = KNOWN_PROBLEMS[0]!;

/** The problem named in a location hash; the default if none is. */
export function problemFromHash(hash: string): string {
  return hashParam(hash, 'problem') ?? DEFAULT_PROBLEM;
}

/** `hash`, changed to name `problem` and nothing else. */
export function hashForProblem(hash: string, problem: string): string {
  return withHashParam(hash, 'problem', problem === DEFAULT_PROBLEM ? null : problem);
}

/**
 * The problem to show out of `available`: the one the visitor chose if it is among them,
 * otherwise the first. A link may name a problem this page has nothing for.
 */
export function chosenProblem(named: string, available: readonly string[]): string {
  return available.includes(named) ? named : available[0] ?? '';
}

/**
 * The problem the visitor chose, kept in the URL so that it survives a change of page and a
 * link carries it. Changing it replaces the history entry rather than adding one.
 */
export function useProblem(): [string, (problem: string) => void] {
  const [problem, setProblem] = useState<string>(() => problemFromHash(window.location.hash));
  useEffect(() => {
    const onHashChange = (): void => setProblem(problemFromHash(window.location.hash));
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);
  return [problem, (next) => {
    window.history.replaceState(window.history.state, '', hashForProblem(window.location.hash, next));
    setProblem(next);
  }];
}
