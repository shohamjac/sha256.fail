"""Command line entry point: `sha-verify <command>`."""

from __future__ import annotations

import argparse
import json
import pathlib
import secrets
import sys

from sha_verifier import __version__, environment, problems, selftest, verify

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


def _cmd_collect(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.results_dir)
    receipts = []
    for path in sorted(root.rglob('*.json')):
        if path.name == INDEX_NAME:
            continue
        receipt = json.loads(path.read_text())
        if not isinstance(receipt, dict) or 'receipt_version' not in receipt:
            raise SystemExit(f'{path} is not a receipt.')
        receipts.append(receipt)
    out = pathlib.Path(args.out) if args.out else root / INDEX_NAME
    out.write_text(json.dumps({'receipts': receipts}, indent=2) + '\n')
    print(f'Wrote {len(receipts)} receipts to {out}', file=sys.stderr)
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
