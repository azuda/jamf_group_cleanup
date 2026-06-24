"""
Entry point: load merge.yaml, resolve groups, execute merges, report results.
"""
import argparse
import os
import sys
import time

import yaml
from jamf_client import get_token, invalidate_token, make_session

from executor import execute
from reporter import print_dry_run, print_results, write_log
from resolver import resolve


def main():
    parser = argparse.ArgumentParser(description="Merge Jamf Pro groups")
    parser.add_argument("--dry", action="store_true", help="Print plan without making changes")
    args = parser.parse_args()

    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "merge.yaml")
    if not os.path.exists(config_path):
        print("merge.yaml not found. Copy merge.yaml.example to merge.yaml and fill it in.", file=sys.stderr)
        sys.exit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    entries = config.get("merges", [])
    if not entries:
        print("No merges defined in merge.yaml.", file=sys.stderr)
        sys.exit(1)

    access_token, expires_in = get_token()
    token = {"t": access_token, "expiration": int(time.time()) + expires_in}
    session = make_session()

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

    finally:
        invalidate_token(access_token)


if __name__ == "__main__":
    main()
