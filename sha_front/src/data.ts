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
    directed_shots: number | null;
    random_shots: number;
    full_strength: boolean;
  };
  verifier: { sha_verifier_version: string; kickmix_version: string };
  submission: {
    name?: string;
    authors?: string[];
    kind?: string;
    description?: string;
    path?: string;
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
  kind: Kind;
  description: string;
  /** Repository path of the submission directory, if known. */
  path: string | null;
  qubits: number;
  toffoli: number;
  score: number;
  operations: number | null;
  reactionDepth: number | null;
  /** ISO timestamp of the verification run. */
  verifiedAt: string;
  directedShots: number;
  randomShots: number;
  /** Repository path of the receipt. */
  receiptPath: string;
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
    };
    const key = `${entry.problem}/${entry.id}`;
    const existing = byId.get(key);
    if (existing === undefined || entry.verifiedAt < existing.verifiedAt) {
      byId.set(key, entry);
    }
  }
  return [...byId.values()];
}

export function problemsOf(entries: Entry[]): string[] {
  return [...new Set(entries.map((e) => e.problem))].sort();
}
