/** Where the project lives. Links to submissions and receipts are built from this. */
export const REPO_URL = 'https://github.com/shohamjac/sha256.fail';
export const REPO_BRANCH = 'main';

export function repoFile(path: string): string {
  return `${REPO_URL}/blob/${REPO_BRANCH}/${path}`;
}

export function repoTree(path: string): string {
  return `${REPO_URL}/tree/${REPO_BRANCH}/${path}`;
}

/**
 * A GitHub account's profile picture, by its numeric user ID. The ID never changes, so the
 * picture survives a change of username. `size` is in CSS pixels; twice that is fetched for
 * sharp rendering on high-density screens.
 */
export function avatarUrl(githubUserId: number, size: number): string {
  return `https://avatars.githubusercontent.com/u/${githubUserId}?s=${2 * size}&v=4`;
}

/**
 * Where a link written inside a submission's notes points. Notes are a README from the
 * submission's directory, so relative links are resolved against that directory in the
 * repository. Returns null for anything that is not a plain web link.
 */
export function noteLink(href: string, submissionPath: string): string | null {
  if (href.startsWith('#')) {
    return null;
  }
  let url: URL;
  try {
    url = new URL(href, `${REPO_URL}/blob/${REPO_BRANCH}/${submissionPath}/`);
  } catch {
    return null;
  }
  return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
}

/**
 * Display titles for the problems the site knows; unknown ones show their id. The order here
 * is the order the problems are offered in, and the first one is shown when the page opens.
 */
export const PROBLEM_TITLES: Record<string, string> = {
  'bitcoin-mining-v1': 'Bitcoin mining oracle',
  'sha256-compress-v1': 'SHA-256 compression',
};

/** The leaderboard page's headline while each problem is shown; `DEFAULT_HEADLINE` for any other. */
export const PROBLEM_HEADLINES: Record<string, string> = {
  'bitcoin-mining-v1': 'How cheaply can a quantum computer mine Bitcoin?',
  'sha256-compress-v1': 'How cheaply can a quantum computer run SHA-256?',
};

export const DEFAULT_HEADLINE = 'How cheaply can a quantum computer run SHA-256?';

/**
 * The fewest qubits a circuit for each problem can have: the qubits of the problem's own
 * registers, which every circuit must contain. The chart marks it; problems not listed here
 * get no mark. `what` names those qubits, to finish the sentence "the fewest qubits a circuit
 * can have: ...".
 *
 * For SHA-256 compression they are the 512-bit block plus the 256-bit digest. The Bitcoin
 * mining oracle is left out for now: its floor, the 80-qubit search register, is far below
 * every submission and would only squash the chart.
 */
export const PROBLEM_MIN_QUBITS: Record<string, { qubits: number; what: string }> = {
  'sha256-compress-v1': { qubits: 768, what: 'the input and output themselves' },
};
