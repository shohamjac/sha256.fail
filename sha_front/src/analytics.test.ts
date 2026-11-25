import { describe, expect, it } from 'vitest';
import { pageLocation } from './analytics';

const origin = 'https://shohamjac.github.io';

describe('pageLocation', () => {
  it('turns the hash route into a path under the site', () => {
    expect(pageLocation(origin, '/sha256.fail/', '#/')).toBe(`${origin}/sha256.fail/`);
    expect(pageLocation(origin, '/sha256.fail/', '#/rules')).toBe(`${origin}/sha256.fail/rules`);
  });

  it('ignores a trailing index.html', () => {
    expect(pageLocation(origin, '/sha256.fail/index.html', '#/submit')).toBe(`${origin}/sha256.fail/submit`);
  });

  it('works at a domain root', () => {
    expect(pageLocation('https://sha256.fail', '/', '#/bitcoin')).toBe('https://sha256.fail/bitcoin');
    expect(pageLocation('https://sha256.fail', '/', '#/')).toBe('https://sha256.fail/');
  });
});
