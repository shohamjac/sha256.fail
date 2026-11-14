"""Command line entry point: `sha-verify <command>`."""

from __future__ import annotations

import argparse
import json
import sys

from sha_verifier import __version__, environment, selftest


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

    p = commands.add_parser('selftest', help='Check the simulator stack and fault detection.')
    p.add_argument('--json', action='store_true', help='Print the full report as JSON.')
    p.set_defaults(func=_cmd_selftest)

    p = commands.add_parser('version', help='Print verifier and simulator versions.')
    p.set_defaults(func=_cmd_version)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
