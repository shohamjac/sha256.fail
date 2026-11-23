/**
 * The site's data: verification receipts written by the backend.
 *
 * `loadReceipts` is the only function that knows where the data comes from. Today that
 * is a static file built from the repository; a hosted service would change this one
 * function to call its API.
 *
 * The receipt format is defined by sha256_verifier/schema/receipt.schema.json. Only the
 * fields the site uses are typed here.
 */

import { PROBLEM_TITLES } from './config';

export interface Receipt {
  receipt_version: number;
  problem: string;
  status: 'PASS' | 'FAIL';
  circuit: {
    sha256: string | null;
    file_sha256: string;
    operations: number | null;
    toffoli_static: number | null;
    reaction_depth: number | null;
  };
  cost: { qubits: number; toffoli: number; score: number; shots: number } | null;
  verification: {
    salt: string;
    seed?: string | null;
    directed_shots: number | null;
    random_shots: number;
    full_strength: boolean;
  };
  verifier: { sha_verifier_version: string; kickmix_version: string };
  submission: {
    name?: string;
    authors?: string[];
    /** The submitter's numeric GitHub user ID. Absent for anonymous submissions. */
    github_user_id?: number;
    kind?: string;
    description?: string;
    path?: string;
    group?: string;
    reference?: string;
    reconstructed_by?: string;
  } | null;
  run: { started_at: string };
}

export type Kind = 'baseline' | 'literature' | 'submission';

/** One verified circuit, as the chart and the leaderboard show it. */
export interface Entry {
  /** SHA-256 of the circuit's canonical form. */
  id: string;
  problem: string;
  name: string;
  authors: string[];
  /** The submitter's numeric GitHub user ID, for their profile picture; null if anonymous. */
  githubUserId: number | null;
  kind: Kind;
  description: string;
  /** Repository path of the submission directory, if known. */
  path: string | null;
  qubits: number;
  toffoli: number;
  /** Qubits times Toffolis, as the receipt records it. A track rescores it; see `scoredOn`. */
  score: number;
  operations: number | null;
  reactionDepth: number | null;
  /** ISO timestamp of the verification run. */
  verifiedAt: string;
  directedShots: number;
  randomShots: number;
  /** Repository path of the receipt. */
  receiptPath: string;
  /** Toffoli-like instructions present in the circuit, whether or not every shot runs them. */
  toffoliStatic: number | null;
  /** Salt of the verification run, recorded so that the run can be replayed. */
  salt: string;
  verifierVersion: string;
  kickmixVersion: string;
  /** The published work a reconstruction is based on, if any. */
  reference: string | null;
  /**
   * Set when several circuits are configurations of one piece of work (one paper or
   * project). Only the best-scoring circuit of a group is listed; see `listed`.
   */
  group: string | null;
  /** On a listed entry: the other verified circuits of its group, best first. */
  otherConfigurations: Entry[];
}

export async function loadReceipts(): Promise<Receipt[]> {
  const response = await fetch(new URL('data/index.json', document.baseURI));
  if (!response.ok) {
    throw new Error(`Could not load results (HTTP ${response.status}).`);
  }
  const body: unknown = await response.json();
  if (typeof body !== 'object' || body === null || !Array.isArray((body as { receipts?: unknown }).receipts)) {
    throw new Error('Results file is not in the expected format.');
  }
  return (body as { receipts: Receipt[] }).receipts;
}

/**
 * A submission's notes: the README.md of its directory, as Markdown. Null if it has none.
 * Like `loadReceipts`, this is the one place that knows where notes are kept.
 */
export async function loadNote(entry: Entry): Promise<string | null> {
  const match = /^submissions\/([a-z0-9][a-z0-9-]*)$/.exec(entry.path ?? '');
  if (match === null) {
    return null;
  }
  const response = await fetch(new URL(`data/notes/${match[1]}.md`, document.baseURI));
  // A missing note may come back as the site's own HTML page rather than a 404.
  if (!response.ok || (response.headers.get('content-type') ?? '').includes('text/html')) {
    return null;
  }
  return response.text();
}

/** A positive whole number, or null: it becomes part of an image URL. */
function asGithubUserId(value: unknown): number | null {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0 ? value : null;
}

function asKind(value: string | undefined): Kind {
  return value === 'baseline' || value === 'literature' ? value : 'submission';
}

/**
 * The circuits that count: those that passed a full-strength run. If a circuit was
 * verified more than once, its earliest passing run is kept, so its date is when it was
 * first verified.
 */
export function toEntries(receipts: Receipt[]): Entry[] {
  const byId = new Map<string, Entry>();
  for (const r of receipts) {
    if (r.status !== 'PASS' || !r.verification.full_strength || r.cost === null || r.circuit.sha256 === null) {
      continue;
    }
    const entry: Entry = {
      id: r.circuit.sha256,
      problem: r.problem,
      name: r.submission?.name?.trim() || `Circuit ${r.circuit.sha256.slice(0, 8)}`,
      authors: r.submission?.authors ?? [],
      githubUserId: asGithubUserId(r.submission?.github_user_id),
      kind: asKind(r.submission?.kind),
      description: r.submission?.description ?? '',
      path: r.submission?.path ?? null,
      qubits: r.cost.qubits,
      toffoli: r.cost.toffoli,
      score: r.cost.score,
      operations: r.circuit.operations,
      reactionDepth: r.circuit.reaction_depth,
      verifiedAt: r.run.started_at,
      directedShots: r.verification.directed_shots ?? 0,
      randomShots: r.verification.random_shots,
      receiptPath: `results/${r.problem}/${r.circuit.sha256}.json`,
      toffoliStatic: r.circuit.toffoli_static,
      salt: r.verification.salt,
      verifierVersion: r.verifier.sha_verifier_version,
      kickmixVersion: r.verifier.kickmix_version,
      reference: r.submission?.reference ?? null,
      group: r.submission?.group?.trim() || null,
      otherConfigurations: [],
    };
    const key = `${entry.problem}/${entry.id}`;
    const existing = byId.get(key);
    if (existing === undefined || entry.verifiedAt < existing.verifiedAt) {
      byId.set(key, entry);
    }
  }
  return [...byId.values()];
}

/**
 * The entries the chart and leaderboard show. Circuits that share a group are different
 * configurations of the same work; of those, only the one with the best score is shown
 * (fewer qubits breaks a tie), and it carries the others in `otherConfigurations`.
 * Ungrouped entries are all shown. Which configuration is best depends on the track, so
 * this is applied to entries already scored on one.
 */
export function listed<T extends Entry>(entries: T[]): T[] {
  const better = (a: T, b: T): number => a.score - b.score || a.qubits - b.qubits;
  const groups = new Map<string, T[]>();
  const out: T[] = [];
  for (const entry of entries) {
    if (entry.group === null) {
      out.push(entry);
      continue;
    }
    const key = `${entry.problem}/${entry.group}`;
    groups.set(key, [...(groups.get(key) ?? []), entry]);
  }
  for (const members of groups.values()) {
    const [best, ...others] = [...members].sort(better);
    out.push({ ...best!, otherConfigurations: others });
  }
  return out;
}

/**
 * The problems that have entries, in the order the site offers them: the problems it knows
 * in the order of `PROBLEM_TITLES`, then any others by id. The first is the default view.
 */
export function problemsOf(entries: Entry[]): string[] {
  const known = Object.keys(PROBLEM_TITLES);
  const place = (problem: string): number => {
    const index = known.indexOf(problem);
    return index === -1 ? known.length : index;
  };
  return [...new Set(entries.map((e) => e.problem))].sort((a, b) => place(a) - place(b) || (a < b ? -1 : 1));
}
