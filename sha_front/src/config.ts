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

/** Display titles for the problems the site knows; unknown ones show their id. */
export const PROBLEM_TITLES: Record<string, string> = {
  'sha256-compress-v1': 'SHA-256 compression',
};
