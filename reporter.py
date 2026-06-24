import os


def print_dry_run(resolved_merges):
    print("DRY RUN — no changes will be made\n")
    for i, rm in enumerate(resolved_merges, 1):
        src_kind = "smart" if rm.source_is_smart else "static"
        print(f"[{i}] {rm.source_name} ({rm.group_type}, {src_kind}) → {rm.target_name}")
        print(f"    Members to add:    {len(rm.delta)}")
        print(f"    Already in target: {len(rm.already_present)}")
        if not rm.delta:
            print("    (no new members — source would not be deleted)")
        print()


def print_results(results):
    for r in results:
        rm = r.resolved
        if r.status == "OK":
            print(f"[OK]   {rm.source_name} → {rm.target_name}  ({len(r.members_added)} added, {len(rm.already_present)} already present)")
        elif r.status == "SKIP":
            print(f"[SKIP] {rm.source_name} → {rm.target_name}  (0 new members, source not deleted)")
        else:
            print(f"[FAIL] {rm.source_name} → {rm.target_name}  ({r.error})")

    ok = sum(1 for r in results if r.status == "OK")
    skip = sum(1 for r in results if r.status == "SKIP")
    fail = sum(1 for r in results if r.status == "FAIL")
    print(f"\n{ok} succeeded, {skip} skipped, {fail} failed")


def write_log(results, log_path):
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
    with open(log_path, "w") as f:
        for r in results:
            rm = r.resolved
            f.write(f"status={r.status} source={rm.source_name}(id={rm.source_id}) target={rm.target_name}(id={rm.target_id}) type={rm.group_type}\n")
            f.write(f"  members_added={r.members_added}\n")
            if r.error:
                f.write(f"  error={r.error}\n")
