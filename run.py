"""
Entry point: load config.yaml, dispatch to merge or scope pipeline.
"""
import argparse
import os
import sys
import time

import yaml
from jamf_client import get_token, invalidate_token, make_session

from executor import execute
from reporter import (
    print_dry_run, print_results, write_log,
    print_scope_dry_run, print_scope_results, write_scope_log,
)
from resolver import resolve
from scope_executor import execute_scope
from scope_resolver import resolve_scope


def _load_config():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    if not os.path.exists(config_path):
        print("config.yaml not found. Copy config.yaml.example to config.yaml and fill it in.", file=sys.stderr)
        sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def _init_auth():
    access_token, expires_in = get_token()
    token = {"t": access_token, "expiration": int(time.time()) + expires_in}
    session = make_session()
    return access_token, token, session


def _cmd_merge(args):
    config = _load_config()
    entries = config.get("merges", [])
    if not entries:
        print("No merges defined in config.yaml.", file=sys.stderr)
        sys.exit(1)

    access_token, token, session = _init_auth()
    try:
        resolved, errors = resolve(entries, token, session)
        if errors:
            for err in errors:
                print(f"Error [entry {err.index + 1}]: {err.message}", file=sys.stderr)
            sys.exit(1)

        if args.dry:
            print_dry_run(resolved)
            return

        results = execute(resolved, token, session)
        print_results(results)

        log_path = os.environ.get("LOG_FILE")
        if log_path:
            write_log(results, log_path)

        if any(r.status == "FAIL" for r in results):
            sys.exit(1)
    finally:
        invalidate_token(access_token)


def _cmd_scope(args):
    config = _load_config()
    entries = config.get("scopes", [])
    if not entries:
        print("No scopes defined in config.yaml.", file=sys.stderr)
        sys.exit(1)

    access_token, token, session = _init_auth()
    try:
        resolved, errors = resolve_scope(entries, token, session)
        if errors:
            for err in errors:
                print(f"Error [entry {err.index + 1}]: {err.message}", file=sys.stderr)
            sys.exit(1)

        if args.dry:
            print_scope_dry_run(resolved)
            return

        results = execute_scope(resolved, token, session)
        print_scope_results(results)

        log_path = os.environ.get("LOG_FILE")
        if log_path:
            write_scope_log(results, log_path)

        if any(r.status == "FAIL" for r in results):
            sys.exit(1)
    finally:
        invalidate_token(access_token)


def main():
    parser = argparse.ArgumentParser(description="Jamf Pro group cleanup")
    sub = parser.add_subparsers(dest="command")
    sub.required = True

    merge_p = sub.add_parser("merge", help="Add source members to target, delete source")
    merge_p.add_argument("--dry", action="store_true", help="Print plan without making changes")

    scope_p = sub.add_parser("scope", help="Replace source group with target in policy/profile scopes")
    scope_p.add_argument("--dry", action="store_true", help="Print plan without making changes")

    args = parser.parse_args()
    if args.command == "merge":
        _cmd_merge(args)
    else:
        _cmd_scope(args)


if __name__ == "__main__":
    main()
