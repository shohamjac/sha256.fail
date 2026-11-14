"""Submissions as they arrive: a directory under `submissions/`, usually in a pull request.

Everything here treats the submission as untrusted data. Nothing in a submission is ever
executed: the only files read are its circuit and its `meta.json`.
"""

from __future__ import annotations

import json
import pathlib
import re
import secrets

from sha_verifier import circuits, problems, verify

CIRCUIT_FILES = ('circuit.kmb', 'circuit.kmx')
META_FILE = 'meta.json'
MAX_META_BYTES = 16 * 1024
KINDS = ('submission', 'baseline', 'literature')

# Lower-case letters, digits and hyphens; starts and ends with a letter or digit.
_NAME = re.compile(r'[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?\Z')
_CONTROL = re.compile(r'[\x00-\x1f\x7f]')

# meta.json fields: name -> (required, maximum length). Lists are checked separately.
_TEXT_FIELDS = {
    'name': (True, 80),
    'description': (True, 1500),
    'problem': (True, 80),
    'kind': (True, 20),
    'path': (True, 120),
    'source': (False, 200),
    'group': (False, 80),
    'reference': (False, 300),
    'reference_commit': (False, 80),
    'reconstructed_by': (False, 80),
}
_LIST_FIELDS = {'authors': (True, 20, 80), 'links': (False, 10, 300)}


class Invalid(Exception):
    """The submission breaks a rule. The message is written for its author."""


class NotASubmission(Exception):
    """The change set is not a submission at all (it touches nothing under `submissions/`)."""


def directory_of_change(changed: list[dict]) -> str:
    """The submission directory a pull request adds.

    Args:
        changed: The pull request's files as GitHub lists them: dicts with `filename` and
            `status`.

    Returns:
        The directory's name, the `<name>` of `submissions/<name>/`.

    Raises:
        NotASubmission: Nothing under `submissions/` is touched.
        Invalid: The pull request is not exactly one new submission directory.
    """
    paths = [str(c['filename']) for c in changed]
    inside = [p for p in paths if p.startswith('submissions/')]
    if not inside:
        raise NotASubmission()
    outside = sorted(set(paths) - set(inside))
    if outside:
        raise Invalid('A submission pull request may only add files under `submissions/<name>/`. '
                      f'This one also touches: {_listing(outside)}.')

    names = set()
    for path in inside:
        parts = path.split('/')
        if len(parts) < 3:
            raise Invalid(f'`{_safe(path)}` is not inside a submission directory.')
        names.add(parts[1])
    if len(names) != 1:
        raise Invalid(f'A pull request may add one submission directory; this one touches {len(names)}.')
    name = names.pop()
    if not _NAME.match(name):
        raise Invalid('The directory name must be 1 to 64 lower-case letters, digits and hyphens, '
                      'starting and ending with a letter or digit.')

    not_added = sorted(str(c['filename']) for c in changed if c.get('status') != 'added')
    if not_added:
        raise Invalid('A submission pull request may only add a new directory, not change or remove '
                      f'existing files: {_listing(not_added)}. To revise a submission, add a new directory.')

    files = {path.removeprefix(f'submissions/{name}/') for path in inside}
    found = [f for f in CIRCUIT_FILES if f in files]
    if len(found) != 1:
        raise Invalid(f'The directory must contain exactly one of {" or ".join(f"`{f}`" for f in CIRCUIT_FILES)}.')
    if META_FILE not in files:
        raise Invalid(f'The directory must contain `{META_FILE}`.')
    return name


def circuit_path(directory: pathlib.Path) -> pathlib.Path:
    found = [directory / f for f in CIRCUIT_FILES if (directory / f).is_file()]
    if len(found) != 1:
        raise Invalid(f'The directory must contain exactly one of {" or ".join(f"`{f}`" for f in CIRCUIT_FILES)}.')
    return found[0]


def load_meta(directory: pathlib.Path, *, external: bool = False) -> dict:
    """Reads and validates `meta.json`.

    Args:
        directory: The submission directory; its name must match the `path` field.
        external: True for a submission from outside the project, which may only be of
            kind `submission`.
    """
    path = directory / META_FILE
    if not path.is_file():
        raise Invalid(f'The directory must contain `{META_FILE}`.')
    raw = path.read_bytes()
    if len(raw) > MAX_META_BYTES:
        raise Invalid(f'`{META_FILE}` is {len(raw)} bytes; the limit is {MAX_META_BYTES}.')
    try:
        meta = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise Invalid(f'`{META_FILE}` is not valid JSON.') from None
    if not isinstance(meta, dict):
        raise Invalid(f'`{META_FILE}` must be a JSON object.')

    unknown = sorted(set(meta) - set(_TEXT_FIELDS) - set(_LIST_FIELDS))
    if unknown:
        raise Invalid(f'`{META_FILE}` has fields that are not recognised: {_listing(unknown)}.')

    def text(field: str, value: object, limit: int) -> None:
        if not isinstance(value, str) or not value.strip() or len(value) > limit or _CONTROL.search(value):
            raise Invalid(f'`{field}` in `{META_FILE}` must be a non-empty string of at most {limit} '
                          'characters with no control characters.')

    for field, (required, limit) in _TEXT_FIELDS.items():
        if field in meta:
            text(field, meta[field], limit)
        elif required:
            raise Invalid(f'`{META_FILE}` must have a `{field}` field.')
    for field, (required, max_items, limit) in _LIST_FIELDS.items():
        if field not in meta:
            if required:
                raise Invalid(f'`{META_FILE}` must have a `{field}` field.')
            continue
        items = meta[field]
        if not isinstance(items, list) or not 1 <= len(items) <= max_items:
            raise Invalid(f'`{field}` in `{META_FILE}` must be a list of 1 to {max_items} strings.')
        for item in items:
            text(field, item, limit)

    if meta['problem'] not in problems.PROBLEMS:
        raise Invalid(f'`problem` must be one of: {_listing(sorted(problems.PROBLEMS))}.')
    if meta['kind'] not in KINDS:
        raise Invalid(f'`kind` must be one of: {_listing(KINDS)}.')
    if external and meta['kind'] != 'submission':
        raise Invalid('`kind` must be `submission`. The other kinds are assigned by the maintainers.')
    if external and 'group' in meta:
        raise Invalid('`group` is assigned by the maintainers; please remove it.')
    expected = f'submissions/{directory.name}'
    if meta['path'] != expected:
        raise Invalid(f'`path` must be `{expected}`, the directory the submission is in.')
    return meta


def check(directory: pathlib.Path, *, external: bool = False) -> tuple[dict, pathlib.Path]:
    """Validates a submission directory's layout and metadata; returns its metadata and circuit path."""
    if not _NAME.match(directory.name):
        raise Invalid('The directory name must be 1 to 64 lower-case letters, digits and hyphens, '
                      'starting and ending with a letter or digit.')
    return load_meta(directory, external=external), circuit_path(directory)


def receipt_path(results_root: pathlib.Path, receipt: dict) -> pathlib.Path:
    """Where a receipt is stored: by the circuit's hash, or the file's if it did not load."""
    name = receipt['circuit']['sha256'] or receipt['circuit']['file_sha256']
    return results_root / receipt['problem'] / f'{name}.json'


def record(submissions_root: pathlib.Path, results_root: pathlib.Path, *, workers: int | None = None,
           random_shots: int | None = None) -> list[dict]:
    """Verifies every submission that has no up-to-date receipt, and writes the receipts.

    A submission is up to date when a receipt exists for its circuit and carries the same
    metadata. Each new run draws a fresh random salt.

    Returns:
        One entry per submission directory: its name and what happened to it
        (`current`, `PASS`, `FAIL` or `invalid`), with a message when invalid.
    """
    outcomes = []
    for directory in sorted(p for p in submissions_root.iterdir() if p.is_dir()):
        try:
            meta, path = check(directory)
        except Invalid as ex:
            outcomes.append({'name': directory.name, 'outcome': 'invalid', 'message': str(ex)})
            continue
        data = path.read_bytes()
        problem = problems.get(meta['problem'])
        try:
            circuit_hash = circuits.load(data).sha256
        except circuits.Rejected:
            circuit_hash = None
        if circuit_hash is not None:
            existing = results_root / problem.name / f'{circuit_hash}.json'
            if existing.is_file() and json.loads(existing.read_text()).get('submission') == meta:
                outcomes.append({'name': directory.name, 'outcome': 'current'})
                continue
        receipt = verify.verify(data, problem, salt=secrets.token_hex(32), random_shots=random_shots,
                                workers=workers, submission=meta)
        target = receipt_path(results_root, receipt)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(receipt, indent=2) + '\n')
        outcomes.append({'name': directory.name, 'outcome': receipt['status']})
    return outcomes


# Pull request comments.

COMMENT_MARKER = '<!-- sha256.fail verification -->'


def _safe(text: object, limit: int = 80) -> str:
    """Untrusted text made safe to place in a Markdown comment: a short, plain string."""
    cleaned = re.sub(r'[^A-Za-z0-9 .,_()/+:-]', '', str(text))
    return cleaned[:limit]


def _listing(items) -> str:
    items = list(items)
    shown = ', '.join(f'`{_safe(item)}`' for item in items[:5])
    return shown + (f' and {len(items) - 5} more' if len(items) > 5 else '')


def _verified(receipts: list[dict], problem: str) -> list[dict]:
    """Full-strength passing receipts for `problem`, one per circuit."""
    by_circuit = {}
    for r in receipts:
        if (r.get('problem') == problem and r.get('status') == 'PASS' and r.get('cost')
                and r['verification'].get('full_strength') and r['circuit'].get('sha256')):
            by_circuit.setdefault(r['circuit']['sha256'], r)
    return list(by_circuit.values())


def _dominates(a: dict, b: dict) -> bool:
    return (a['qubits'] <= b['qubits'] and a['toffoli'] <= b['toffoli']
            and (a['qubits'] < b['qubits'] or a['toffoli'] < b['toffoli']))


def _number(value: float) -> str:
    return f'{value:,.0f}' if float(value).is_integer() else f'{value:,.1f}'


def summarize(receipt: dict, index: list[dict]) -> str:
    """A Markdown summary of a verification result, comparing it with the verified circuits."""
    lines = [COMMENT_MARKER]
    if receipt['status'] != 'PASS':
        failure = receipt['failure']
        lines += [
            '### Verification failed',
            '',
            f"The circuit was rejected at the **{_safe(failure['stage'])}** stage: {_safe(failure['message'], 400)}",
            '',
            f"- Check: `{_safe(failure['code'])}`",
        ]
        if failure.get('shot') is not None:
            lines.append(f"- First failing test: number {int(failure['shot'])} of the {_safe(failure['stage'])} tests")
        for register, value in (failure.get('inputs') or {}).items():
            lines.append(f'- Input `{_safe(register)}` of that test (register bits, hex): `{_safe(value, 200)}`')
        lines += ['', 'Run `sha-verify run` on the circuit to reproduce this locally.']
        return '\n'.join(lines) + '\n'

    cost = receipt['cost']
    others = [r for r in _verified(index, receipt['problem']) if r['circuit']['sha256'] != receipt['circuit']['sha256']]
    dominating = [r for r in others if _dominates(r['cost'], cost)]
    beaten = [r for r in others if _dominates(cost, r['cost'])]
    best = min(others, key=lambda r: r['cost']['score'], default=None)

    lines += [
        '### Verification passed',
        '',
        '| Qubits | Toffolis per shot | Score |',
        '|---:|---:|---:|',
        f"| {_number(cost['qubits'])} | {_number(cost['toffoli'])} | {_number(cost['score'])} |",
        '',
    ]
    if dominating:
        lines.append(f'**Dominated** by {len(dominating)} verified circuit{"s" if len(dominating) != 1 else ""}: '
                     'at least one has no more qubits and no more Toffolis.')
    else:
        lines.append('**On the Pareto front**: no verified circuit has both no more qubits and no more Toffolis.')
        if beaten:
            lines.append(f'It dominates {len(beaten)} verified circuit{"s" if len(beaten) != 1 else ""}.')
    if best is None:
        lines.append('It is the first verified circuit for this problem.')
    elif cost['score'] < best['cost']['score']:
        gain = 100 * (1 - cost['score'] / best['cost']['score'])
        lines.append(f"**New best score**, {gain:.1f}% below the current best of {_number(best['cost']['score'])}.")
    else:
        lines.append(f"The current best score is {_number(best['cost']['score'])}.")

    checks = receipt['verification']
    lines += [
        '',
        f"Checked on {_number(checks['directed_shots'])} directed and {_number(checks['random_shots'])} random tests, "
        'all correct. '
        + ('' if checks['full_strength'] else '**This was a reduced run, not a full-strength one.** ')
        + f"Circuit `{_safe(receipt['circuit']['sha256'])[:16]}`, salt `{_safe(checks['salt'])[:16]}…`.",
        '',
        'This is a check of the pull request. The receipt that counts is produced when it is merged, '
        'with a new salt.',
    ]
    return '\n'.join(lines) + '\n'


def summarize_invalid(message: str) -> str:
    """The comment for a pull request that is not a well-formed submission."""
    return '\n'.join([
        COMMENT_MARKER,
        '### Submission not verified',
        '',
        message,
        '',
        'See the Submit page of the site, or `submissions/example/`, for the expected layout.',
    ]) + '\n'
