import { describe, expect, it } from 'vitest';
import { noteLink } from './config';

const base = 'https://github.com/shohamjac/sha256.fail/blob/main';

describe('noteLink', () => {
  it('resolves relative links against the submission directory in the repository', () => {
    expect(noteLink('build.py', 'submissions/example')).toBe(`${base}/submissions/example/build.py`);
    expect(noteLink('../example', 'submissions/low-qubit-adder')).toBe(`${base}/submissions/example`);
    expect(noteLink('../../results/index.json', 'submissions/example')).toBe(`${base}/results/index.json`);
  });

  it('keeps absolute web links', () => {
    expect(noteLink('https://arxiv.org/abs/quant-ph/0410184', 'submissions/x')).toBe(
      'https://arxiv.org/abs/quant-ph/0410184');
  });

  it('refuses anything that is not a web link', () => {
    expect(noteLink('javascript:alert(1)', 'submissions/x')).toBeNull();
    expect(noteLink('data:text/html,<script>1</script>', 'submissions/x')).toBeNull();
    expect(noteLink('#section', 'submissions/x')).toBeNull();
    expect(noteLink('mailto:a@b.c', 'submissions/x')).toBeNull();
  });
});
