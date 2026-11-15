import { useEffect, useRef, useState, type MouseEvent, type ReactElement } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { noteLink, repoFile, repoTree } from '../config';
import { loadNote, type Kind } from '../data';
import { compact, count, date } from '../format';
import { dominates, ranked } from '../pareto';
import type { Scored, Track } from '../tracks';

const KIND_BADGE: Record<Kind, string> = {
  submission: 'Submission',
  baseline: 'Reference construction',
  literature: 'Reconstruction of published work',
};

type Note = { state: 'loading' } | { state: 'none' } | { state: 'ready'; text: string };

interface Props {
  /** The circuit to show, or null when the dialog is closed. */
  entry: Scored | null;
  /** Every listed circuit of the same problem, for rank and Pareto status. */
  entries: Scored[];
  /** The track the page shows; the score and rank are on it. */
  track: Track;
  onClose: () => void;
}

/**
 * A modal with one circuit's numbers, how it was verified, and its notes.
 *
 * Built on the native dialog element, which provides the backdrop, keeps keyboard focus
 * inside while open, and closes on Escape.
 */
export function SubmissionDialog({ entry, entries, track, onClose }: Props): ReactElement {
  const dialog = useRef<HTMLDialogElement | null>(null);
  const [note, setNote] = useState<Note>({ state: 'loading' });

  useEffect(() => {
    const element = dialog.current;
    if (element === null) {
      return;
    }
    if (entry !== null && !element.open) {
      element.showModal();
      // Start focus on the sheet rather than the close button, so no focus ring shows
      // until the keyboard is used.
      element.querySelector<HTMLElement>('.sheet')?.focus();
    } else if (entry === null && element.open) {
      element.close();
    }
  }, [entry]);

  useEffect(() => {
    if (entry === null) {
      return;
    }
    let current = true;
    setNote({ state: 'loading' });
    loadNote(entry)
      .then((text) => {
        if (current) {
          setNote(text === null ? { state: 'none' } : { state: 'ready', text });
        }
      })
      .catch(() => {
        if (current) {
          setNote({ state: 'none' });
        }
      });
    return () => {
      current = false;
    };
  }, [entry]);

  // A click on the dialog element itself, rather than on its content, is a click on the backdrop.
  function onBackdrop(event: MouseEvent<HTMLDialogElement>): void {
    if (event.target === dialog.current) {
      onClose();
    }
  }

  return (
    <dialog ref={dialog} className="submission" onClose={onClose} onClick={onBackdrop}
      aria-labelledby="submission-title">
      {entry !== null && <Content entry={entry} entries={entries} track={track} note={note} onClose={onClose} />}
    </dialog>
  );
}

function Content({ entry, entries, track, note, onClose }: {
  entry: Scored;
  entries: Scored[];
  track: Track;
  note: Note;
  onClose: () => void;
}): ReactElement {
  const rank = ranked(entries).findIndex((e) => e.id === entry.id) + 1;
  const dominatedBy = entries.filter((other) => dominates(other, entry)).length;
  const path = entry.path;

  return (
    <div className="sheet" tabIndex={-1}>
      <header>
        <div className="who">
          <h2 id="submission-title">{entry.name}</h2>
          <div className="byline">
            {entry.authors.length > 0 && <span>{entry.authors.join(', ')}</span>}
            <span className="kind">{KIND_BADGE[entry.kind]}</span>
          </div>
        </div>
        <button type="button" className="close" onClick={onClose} aria-label="Close">
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
            <path d="M3 3l10 10M13 3L3 13" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </button>
      </header>

      <div className="scroll">
        <div className="facts">
          <div className="fact">
            <div className="label">Score, {track.label.toLowerCase()}</div>
            <div className="value">{count(entry.score)}</div>
            <div className="sub">{count(entry.cost)} {track.symbol} × {count(entry.qubits)} Q</div>
          </div>
          <div className="fact">
            <div className="label">Rank</div>
            <div className="value">{rank > 0 ? `${rank} of ${entries.length}` : '–'}</div>
            <div className="sub">
              {dominatedBy === 0
                ? 'On the Pareto front'
                : `Dominated by ${dominatedBy} circuit${dominatedBy === 1 ? '' : 's'}`}
            </div>
          </div>
          <div className="fact">
            <div className="label">Verified</div>
            <div className="value">{date(entry.verifiedAt)}</div>
            <div className="sub">{count(entry.directedShots + entry.randomShots)} tests, all correct</div>
          </div>
        </div>

        {entry.description !== '' && <p className="description">{entry.description}</p>}

        <h3>Parameters</h3>
        <dl className="parameters">
          <dt>Qubits</dt>
          <dd>{count(entry.qubits)}</dd>
          <dt>Toffolis per shot</dt>
          <dd>
            {count(entry.toffoli)}
            {entry.toffoliStatic !== null && entry.toffoliStatic !== entry.toffoli && (
              <span className="aside"> mean; {count(entry.toffoliStatic)} in the circuit</span>
            )}
          </dd>
          {entry.reactionDepth !== null && (
            <>
              <dt>Reaction depth</dt>
              <dd>{count(entry.reactionDepth)}</dd>
            </>
          )}
          {entry.operations !== null && (
            <>
              <dt>Operations</dt>
              <dd>{count(entry.operations)}</dd>
            </>
          )}
          <dt>Tests passed</dt>
          <dd>{count(entry.directedShots)} directed, {count(entry.randomShots)} random</dd>
          <dt>Salt</dt>
          <dd className="mono wrap">{entry.salt === '' ? '(empty)' : entry.salt}</dd>
          <dt>Circuit SHA-256</dt>
          <dd className="mono wrap">{entry.id}</dd>
          <dt>Verifier</dt>
          <dd>sha-verifier {entry.verifierVersion}, Kickmix {entry.kickmixVersion}</dd>
          {entry.reference !== null && noteLink(entry.reference, path ?? '') !== null && (
            <>
              <dt>Based on</dt>
              <dd><a href={noteLink(entry.reference, path ?? '')!} target="_blank" rel="noreferrer">{entry.reference}</a></dd>
            </>
          )}
          <dt>Links</dt>
          <dd className="links">
            {path !== null && <a href={repoTree(path)} target="_blank" rel="noreferrer">circuit files</a>}
            <a href={repoFile(entry.receiptPath)} target="_blank" rel="noreferrer">verification receipt</a>
          </dd>
        </dl>

        {entry.otherConfigurations.length > 0 && (
          <p className="others">
            Other verified configurations of the same work, not listed because this one scores better:{' '}
            {entry.otherConfigurations.map((other, i) => (
              <span key={other.id}>
                {i > 0 && '; '}
                {other.name} ({count(other.qubits)} qubits, {count(track.cost(other) ?? 0)} {track.costNoun}, score{' '}
                {compact(other.score)},{' '}
                {other.path !== null && <><a href={repoTree(other.path)} target="_blank" rel="noreferrer">files</a>, </>}
                <a href={repoFile(other.receiptPath)} target="_blank" rel="noreferrer">receipt</a>)
              </span>
            ))}
            .
          </p>
        )}

        <h3>Note</h3>
        <div className="note">
          {note.state === 'loading' && <p className="muted">Loading…</p>}
          {note.state === 'none' && <p className="muted">This submission has no notes.</p>}
          {note.state === 'ready' && (
            // Notes are written by submitters. Raw HTML in them is not rendered (the
            // renderer shows it as text), images are dropped, and links are restricted
            // to web addresses.
            <Markdown
              remarkPlugins={[remarkGfm]}
              disallowedElements={['img']}
              urlTransform={(url) => noteLink(url, path ?? '') ?? ''}
              components={{
                a: ({ href, children }) =>
                  href ? <a href={href} target="_blank" rel="noreferrer nofollow">{children}</a> : <>{children}</>,
                table: ({ children }) => <div className="table-scroll"><table>{children}</table></div>,
              }}
            >
              {note.text}
            </Markdown>
          )}
        </div>
      </div>
    </div>
  );
}
