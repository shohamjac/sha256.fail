import { useEffect, useState, type ReactElement } from 'react';
import { REPO_URL } from './config';
import { loadReceipts, toEntries, type Entry } from './data';
import { Home } from './pages/Home';
import { Rules } from './pages/Rules';
import { Submit } from './pages/Submit';
import { Verification } from './pages/Verification';

const PAGES = [
  { hash: '#/', label: 'Leaderboard' },
  { hash: '#/rules', label: 'The task' },
  { hash: '#/submit', label: 'Submit' },
  { hash: '#/verification', label: 'Verification' },
] as const;

type Route = (typeof PAGES)[number]['hash'];

function currentRoute(): Route {
  const hash = window.location.hash;
  return PAGES.find((page) => page.hash === hash)?.hash ?? '#/';
}

type Data = { state: 'loading' } | { state: 'error'; message: string } | { state: 'ready'; entries: Entry[] };

export function App(): ReactElement {
  const [route, setRoute] = useState<Route>(currentRoute);
  const [data, setData] = useState<Data>({ state: 'loading' });

  useEffect(() => {
    const onHashChange = (): void => {
      setRoute(currentRoute());
      window.scrollTo(0, 0);
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  useEffect(() => {
    loadReceipts()
      .then((receipts) => setData({ state: 'ready', entries: toEntries(receipts) }))
      .catch((error: unknown) =>
        setData({ state: 'error', message: error instanceof Error ? error.message : String(error) }));
  }, []);

  return (
    <div className="shell">
      <header className="site-header">
        <a className="site-name" href="#/">sha256.fail</a>
        <nav className="site-nav" aria-label="Pages">
          {PAGES.map((page) => (
            <a key={page.hash} href={page.hash} aria-current={route === page.hash ? 'page' : undefined}>
              {page.label}
            </a>
          ))}
        </nav>
        <a className="repo" href={REPO_URL}>GitHub</a>
      </header>

      <main>
        {route === '#/rules' && <Rules />}
        {route === '#/submit' && <Submit />}
        {route === '#/verification' && <Verification />}
        {route === '#/' && (
          <>
            {data.state === 'loading' && <p className="notice">Loading results…</p>}
            {data.state === 'error' && <p className="notice" role="alert">{data.message}</p>}
            {data.state === 'ready' && <Home entries={data.entries} />}
          </>
        )}
      </main>

      <footer className="site-footer">
        Verified with Google's Kickmix simulator. Code and results are in the{' '}
        <a href={REPO_URL}>repository</a>.
      </footer>
    </div>
  );
}
