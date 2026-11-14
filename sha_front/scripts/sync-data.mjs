// Copies the site's data out of the repository into its static files:
//   data/index.json            the verifier's receipts
//   data/notes/<directory>.md  each submission's README.md, shown as its notes
// The site reads these and nothing else.
import { copyFileSync, existsSync, mkdirSync, readFileSync, rmSync, statSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, '../..');
const out = resolve(here, '../public/data');
const MAX_NOTE_BYTES = 200 * 1024;

mkdirSync(out, { recursive: true });
copyFileSync(resolve(repo, 'results/index.json'), resolve(out, 'index.json'));

// Notes come from submitted directories, so the path each receipt names is checked before
// it is used: exactly `submissions/<name>`, with a plain directory name.
rmSync(resolve(out, 'notes'), { recursive: true, force: true });
mkdirSync(resolve(out, 'notes'));
const { receipts } = JSON.parse(readFileSync(resolve(repo, 'results/index.json'), 'utf8'));
let notes = 0;
for (const receipt of receipts) {
  const match = /^submissions\/([a-z0-9][a-z0-9-]*)$/.exec(receipt.submission?.path ?? '');
  if (match === null) {
    continue;
  }
  const readme = resolve(repo, 'submissions', match[1], 'README.md');
  if (existsSync(readme) && statSync(readme).size <= MAX_NOTE_BYTES) {
    copyFileSync(readme, resolve(out, 'notes', `${match[1]}.md`));
    notes += 1;
  }
}
console.log(`Copied ${receipts.length} receipts and ${notes} notes into ${out}`);
