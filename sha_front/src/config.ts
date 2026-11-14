/** Where the project lives. Links to submissions and receipts are built from this. */
export const REPO_URL = 'https://github.com/shohamjac/sha256.fail';
export const REPO_BRANCH = 'main';

export function repoFile(path: string): string {
  return `${REPO_URL}/blob/${REPO_BRANCH}/${path}`;
}

export function repoTree(path: string): string {
  return `${REPO_URL}/tree/${REPO_BRANCH}/${path}`;
}

/** Display titles for the problems the site knows; unknown ones show their id. */
export const PROBLEM_TITLES: Record<string, string> = {
  'sha256-compress-v1': 'SHA-256 compression',
};
