"""Command line entry point: `sha-verify <command>`."""

from __future__ import annotations

import argparse
import json
import pathlib
import secrets
import sys

from sha_verifier import __version__, environment, problems, selftest, submission, verify

INDEX_NAME = 'index.json'


def _cmd_run(args: argparse.Namespace) -> int:
    problem = problems.get(args.problem)
    data = pathlib.Path(args.circuit).read_bytes()
    submission = None
    if args.meta:
        submission = json.loads(pathlib.Path(args.meta).read_text())
        if not isinstance(submission, dict):
            raise SystemExit(f'{args.meta} must contain a JSON object.')
    salt = secrets.token_hex(32) if args.random_salt else args.salt

    receipt = verify.verify(data, problem, salt=salt, random_shots=args.shots,
                            workers=args.workers, submission=submission)
    text = json.dumps(receipt, indent=2) + '\n'
    if args.results_dir:
        # Named by the circuit's canonical hash, or by the file's hash if it did not load.
        name = receipt['circuit']['sha256'] or receipt['circuit']['file_sha256']
        path = pathlib.Path(args.results_dir) / problem.name / f'{name}.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        print(f'Wrote {path}', file=sys.stderr)
    sys.stdout.write(text)
    return 0 if receipt['status'] == 'PASS' else 1


def _cmd_replay(args: argparse.Namespace) -> int:
    recorded = json.loads(pathlib.Path(args.receipt).read_text())
    problem = problems.get(recorded['problem'])
    data = pathlib.Path(args.circuit).read_bytes()
    replayed = verify.verify(data, problem, salt=recorded['verification']['salt'],
                             random_shots=recorded['verification']['random_shots'],
                             workers=args.workers, submission=recorded['submission'])
    # The verifier version is reported separately: a newer verifier may still agree.
    ignored = ('run', 'verifier')
    differing = sorted(key for key in recorded.keys() | replayed.keys()
                       if key not in ignored and recorded.get(key) != replayed.get(key))
    if recorded['verifier'] != replayed['verifier']:
        print(f"Note: receipt was made by {recorded['verifier']}, this is {replayed['verifier']}.", file=sys.stderr)
    if differing:
        print(f"MISMATCH in: {', '.join(differing)}")
        for key in differing:
            print(f'  {key}:\n    recorded: {json.dumps(recorded.get(key))}\n    replayed: {json.dumps(replayed.get(key))}')
        return 1
    print(f"MATCH: {replayed['status']}, {replayed['verification']['random_shots']} random shots, "
          f"circuit {replayed['circuit']['file_sha256'][:16]}")
    return 0


def _read_index(path: str | None) -> list[dict]:
    if not path or not pathlib.Path(path).is_file():
        return []
    return json.loads(pathlib.Path(path).read_text())['receipts']


def _cmd_check_submission(args: argparse.Namespace) -> int:
    try:
        meta, circuit = submission.check(pathlib.Path(args.directory), external=args.external)
    except submission.Invalid as ex:
        print(f'Invalid submission: {ex}', file=sys.stderr)
        return 1
    print(f"OK: {meta['name']} ({circuit.name}) for {meta['problem']}")
    return 0


def _cmd_pr_check(args: argparse.Namespace) -> int:
    """Exit 0 and print the directory name; 1 if the pull request is malformed (the reason
    is written as a comment to --comment); 3 if it is not a submission at all."""
    changed = json.loads(pathlib.Path(args.changed).read_text())
    try:
        name = submission.directory_of_change(changed)
    except submission.NotASubmission:
        print('Not a submission pull request.', file=sys.stderr)
        return 3
    except submission.Invalid as ex:
        pathlib.Path(args.comment).write_text(submission.summarize_invalid(str(ex)))
        print(f'Invalid submission: {ex}', file=sys.stderr)
        return 1
    print(name)
    return 0


def _cmd_pr_verify(args: argparse.Namespace) -> int:
    """Checks and verifies one submission directory from a pull request. Always writes a
    comment to --comment; writes the receipt to --receipt when the circuit was verified."""
    comment = pathlib.Path(args.comment)
    try:
        meta, circuit = submission.check(pathlib.Path(args.directory), external=True)
    except submission.Invalid as ex:
        comment.write_text(submission.summarize_invalid(str(ex)))
        print(f'Invalid submission: {ex}', file=sys.stderr)
        return 1
    receipt = verify.verify(circuit.read_bytes(), problems.get(meta['problem']), salt=secrets.token_hex(32),
                            random_shots=args.shots, workers=args.workers, submission=meta)
    pathlib.Path(args.receipt).write_text(json.dumps(receipt, indent=2) + '\n')
    comment.write_text(submission.summarize(receipt, _read_index(args.index)))
    print(f"{receipt['status']}: {circuit}", file=sys.stderr)
    return 0 if receipt['status'] == 'PASS' else 1


def _cmd_summarize(args: argparse.Namespace) -> int:
    receipt = json.loads(pathlib.Path(args.receipt).read_text())
    sys.stdout.write(submission.summarize(receipt, _read_index(args.index)))
    return 0


def _cmd_record(args: argparse.Namespace) -> int:
    results = pathlib.Path(args.results_dir)
    outcomes = submission.record(pathlib.Path(args.submissions_dir), results, workers=args.workers)
    for outcome in outcomes:
        print(f"{outcome['outcome']:8s} {outcome['name']}" + (f": {outcome['message']}" if 'message' in outcome else ''))
    _write_index(results, results / INDEX_NAME)
    return 1 if any(o['outcome'] == 'invalid' for o in outcomes) else 0


def _write_index(root: pathlib.Path, out: pathlib.Path) -> int:
    receipts = []
    for path in sorted(root.rglob('*.json')):
        if path.name == INDEX_NAME:
            continue
        receipt = json.loads(path.read_text())
        if not isinstance(receipt, dict) or 'receipt_version' not in receipt:
            raise SystemExit(f'{path} is not a receipt.')
        receipts.append(receipt)
    out.write_text(json.dumps({'receipts': receipts}, indent=2) + '\n')
    return len(receipts)


def _cmd_collect(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.results_dir)
    out = pathlib.Path(args.out) if args.out else root / INDEX_NAME
    count = _write_index(root, out)
    print(f'Wrote {count} receipts to {out}', file=sys.stderr)
    return 0


def _cmd_selftest(args: argparse.Namespace) -> int:
    report = selftest.run()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for check in report['checks']:
            print(f"{check['status']}  {check['name']}: {check['detail']}")
        env = report['environment']
        print(f"\nkickmix {env['kickmix_version']} ({env['kickmix_binary_sha256'][:16]}), "
              f"python {env['python_version']}, {env['machine']}")
        print(f"selftest: {report['status']}")
    return 0 if report['status'] == 'PASS' else 1


def _cmd_version(args: argparse.Namespace) -> int:
    print(json.dumps({'sha_verifier_version': __version__, **environment.describe()}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='sha-verify', description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)

    p = commands.add_parser(
        'run', help='Verify a circuit file and print its receipt.',
        description='Verify a circuit file against a problem. Prints the receipt as JSON; '
                    'exits 0 if the circuit passed and 1 if it failed.')
    p.add_argument('circuit', help='Path to a .kmb or .kmx circuit file.')
    p.add_argument('--problem', default=problems.SHA256_COMPRESS_V1.name,
                   choices=sorted(problems.PROBLEMS), help='Problem to verify against (default: %(default)s).')
    salt = p.add_mutually_exclusive_group()
    salt.add_argument('--salt', default='',
                      help='Salt mixed into the seed that selects the random tests (default: empty).')
    salt.add_argument('--random-salt', action='store_true',
                      help='Draw a fresh random salt; it is recorded in the receipt.')
    p.add_argument('--shots', type=int, default=None,
                   help="Random test inputs (default: the problem's full-strength count).")
    p.add_argument('--workers', type=int, default=None, help='Worker processes (default: all cores).')
    p.add_argument('--meta', help='JSON file with submission metadata to carry in the receipt.')
    p.add_argument('--results-dir',
                   help='Also write the receipt to <results-dir>/<problem>/<circuit sha256>.json.')
    p.set_defaults(func=_cmd_run)

    p = commands.add_parser(
        'replay', help='Re-run a verification from its receipt and compare.',
        description='Verify a circuit again with the salt and shot count recorded in a receipt, and '
                    'check that the result is identical. Exits 0 on a match and 1 otherwise.')
    p.add_argument('receipt', help='Path to a receipt JSON file.')
    p.add_argument('circuit', help='Path to the circuit file the receipt is for.')
    p.add_argument('--workers', type=int, default=None, help='Worker processes (default: all cores).')
    p.set_defaults(func=_cmd_replay)

    p = commands.add_parser('check-submission', help='Check a submission directory\'s layout and meta.json.')
    p.add_argument('directory', help='A directory under submissions/.')
    p.add_argument('--external', action='store_true',
                   help='Apply the rules for submissions from outside the project.')
    p.set_defaults(func=_cmd_check_submission)

    p = commands.add_parser(
        'record', help='Verify every submission without an up-to-date receipt and write the receipts.',
        description='For each directory under SUBMISSIONS_DIR whose circuit has no receipt carrying its current '
                    'metadata, run a full-strength verification with a fresh random salt and write the receipt. '
                    f'Then rebuild {INDEX_NAME}. Never runs any code from a submission.')
    p.add_argument('submissions_dir')
    p.add_argument('results_dir')
    p.add_argument('--workers', type=int, default=None, help='Worker processes (default: all cores).')
    p.set_defaults(func=_cmd_record)

    p = commands.add_parser('summarize', help='Print a Markdown summary of a receipt.')
    p.add_argument('receipt')
    p.add_argument('--index', help=f'An {INDEX_NAME} to compare against.')
    p.set_defaults(func=_cmd_summarize)

    p = commands.add_parser('pr-check', help='For CI: find the submission directory a pull request adds.')
    p.add_argument('changed', help='JSON list of the pull request\'s files, as the GitHub API returns it.')
    p.add_argument('--comment', required=True, help='Where to write the comment if the pull request is malformed.')
    p.set_defaults(func=_cmd_pr_check)

    p = commands.add_parser('pr-verify', help='For CI: check and verify a submission from a pull request.')
    p.add_argument('directory', help='The submission directory, extracted from the pull request.')
    p.add_argument('--receipt', required=True, help='Where to write the receipt.')
    p.add_argument('--comment', required=True, help='Where to write the Markdown comment.')
    p.add_argument('--index', help=f'An {INDEX_NAME} to compare against.')
    p.add_argument('--shots', type=int, default=None, help='Random tests (default: full strength).')
    p.add_argument('--workers', type=int, default=None)
    p.set_defaults(func=_cmd_pr_verify)

    p = commands.add_parser('collect', help=f'Gather every receipt under a directory into {INDEX_NAME}.')
    p.add_argument('results_dir', help='Directory holding receipts.')
    p.add_argument('--out', help=f'Output file (default: <results_dir>/{INDEX_NAME}).')
    p.set_defaults(func=_cmd_collect)

    p = commands.add_parser('selftest', help='Check the simulator stack and fault detection.')
    p.add_argument('--json', action='store_true', help='Print the full report as JSON.')
    p.set_defaults(func=_cmd_selftest)

    p = commands.add_parser('version', help='Print verifier and simulator versions.')
    p.set_defaults(func=_cmd_version)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
