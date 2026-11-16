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
 * The fewest qubits a circuit for each problem can have: the problem's own registers, which
 * every circuit must contain. For SHA-256 compression that is the 512-bit block plus the
 * 256-bit digest. The chart marks it; problems not listed here get no mark.
 */
export const PROBLEM_MIN_QUBITS: Record<string, number> = {
  'sha256-compress-v1': 768,
};

/** Display titles for the problems the site knows; unknown ones show their id. */
export const PROBLEM_TITLES: Record<string, string> = {
  'sha256-compress-v1': 'SHA-256 compression',
};
