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


def print_scope_dry_run(resolved_scopes):
    print("DRY RUN — no changes will be made\n")
    for i, rs in enumerate(resolved_scopes, 1):
        print(f"[{i}] {rs.source_name} ({rs.group_type}) → {rs.target_name}")
        policies = [o for o in rs.objects if o.object_type == "policy" and not o.target_already_present]
        osx = [o for o in rs.objects if o.object_type == "osx_profile" and not o.target_already_present]
        mobile = [o for o in rs.objects if o.object_type == "mobile_profile" and not o.target_already_present]
        noop = [o for o in rs.objects if o.target_already_present]

        if rs.group_type == "computer":
            print(f"    computer policies:     {len(policies)} would be updated")
            print(f"    macOS config profiles: {len(osx)} would be updated")
        else:
            print(f"    mobile device profiles: {len(mobile)} would be updated")

        if noop:
            print(f"    Already has target:    {len(noop)} object(s) (no-op)")
        if not rs.objects:
            print("    (source group not found in any scope — would be skipped)")
        print()


def print_scope_results(results):
    for r in results:
        rs = r.resolved
        n = len(r.objects_updated)
        if r.status == "OK":
            print(f"[OK]   {rs.source_name} → {rs.target_name}  ({n} object{'s' if n != 1 else ''} updated)")
        elif r.status == "SKIP":
            if r.skip_reason == "all_noop":
                print(f"[SKIP] {rs.source_name} → {rs.target_name}  (target group already present in all matching scopes)")
            else:
                print(f"[SKIP] {rs.source_name} → {rs.target_name}  (source group not found in any scope)")
        else:
            print(f"[FAIL] {rs.source_name} → {rs.target_name}  ({r.error})")

    ok = sum(1 for r in results if r.status == "OK")
    skip = sum(1 for r in results if r.status == "SKIP")
    fail = sum(1 for r in results if r.status == "FAIL")
    print(f"\n{ok} succeeded, {skip} skipped, {fail} failed")


def write_scope_log(results, log_path):
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
    with open(log_path, "a") as f:
        for r in results:
            rs = r.resolved
            f.write(f"scope: status={r.status} source={rs.source_name}(id={rs.source_id}) target={rs.target_name}(id={rs.target_id}) type={rs.group_type}\n")
            for obj in r.objects_updated:
                f.write(f"  updated: {obj.object_type} '{obj.object_name}' (id={obj.object_id})\n")
            if r.objects_updated:
                f.write(f"  DEPRECATED: '{rs.source_name}' (id={rs.source_id}) scope references replaced by '{rs.target_name}' (id={rs.target_id}) — group not deleted\n")
            if r.error:
                f.write(f"  error={r.error}\n")
