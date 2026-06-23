# Jamf Group Cleanup — Design Spec

**Date:** 2026-06-23
**Status:** Approved

---

## Overview

A config-driven Python script that merges Jamf Pro groups. The user specifies source→target merge pairs in a YAML file. The tool validates everything upfront, then adds all source members to the target and deletes the source group. Supports computer and mobile device groups (smart and static).

---

## YAML Config Format

File: `merge.yaml` (gitignored, user-maintained)

```yaml
merges:
  - source: "Old Staff Macs"        # string = name lookup
    target: "All Staff Computers"
    type: computer

  - source: 4821                    # integer = direct ID lookup
    target: "All Student iPads"
    type: mobile_device

  - source: "Retired iPad Pool"
    target: "All Student iPads"
    type: mobile_device
```

**Fields:**
- `source`: group name (string) or Jamf ID (integer). Name preferred; ID used when name lookup is ambiguous or unavailable.
- `target`: same as source.
- `type`: required. Must be `computer` or `mobile_device`.

---

## Execution Phases

### Phase 1 — Resolution & Validation (always runs)

For each merge entry:
1. Look up source and target via the Jamf classic API (`/JSSResource/computergroups` or `/JSSResource/mobiledevicegroups`) by name or ID.
2. Determine whether each group is smart or static (`is_smart` field).
3. For smart source groups: fetch the current evaluated member list (snapshot at run time).
4. For static source groups: fetch the explicit member list.

**Validation rules — all checked before any writes:**
- Source group must exist. Error if not found.
- Target group must exist. Error if not found.
- Target must be a static group. Error if target is smart (can't add explicit members).
- Source and target must not be the same group. Error if IDs match.

All validation errors are collected and printed together. The script exits with a non-zero code if any validation fails — nothing is written.

### Phase 2 — Dry-run output (if `--dry` flag is passed)

Print a human-readable plan for each merge entry:
- Source group name, type (computer/mobile), group kind (smart/static)
- Target group name
- Members that would be added (delta: in source, not already in target)
- Members already present in target (skipped)

Exit with code 0 after printing. No API writes are made.

### Phase 3 — Execution (if not `--dry`)

For each merge entry in order:
1. Fetch the current member list of the target static group.
2. Compute delta: source members not already in target.
3. If delta is empty: mark as `SKIP`, do not delete source.
4. PUT the full updated member list to the target group (classic API).
5. If PUT fails: retry once. If retry fails: mark as `FAIL`, log error, continue to next entry. Do not delete source.
6. If PUT succeeds: DELETE the source group.
7. Mark as `OK`.

Entries are processed in YAML order. A failure in one entry does not block subsequent entries.

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| Group not found (source or target) | Fatal — collected with all other validation errors, printed together, exit before Phase 3 |
| Target is a smart group | Fatal — same as above |
| Source == target | Fatal — same as above |
| PUT fails on first attempt | Retry once |
| PUT fails on retry | Log error, mark FAIL, skip DELETE, continue |
| DELETE fails | Members were added successfully; log error, mark FAIL, source group left in place |

---

## Output & Logging

**Console summary (end of run):**
```
[OK]   Old Staff Macs → All Staff Computers  (42 added, 3 already present)
[SKIP] Retired iPad Pool → All Student iPads  (0 new members, source not deleted)
[FAIL] Old Lab Macs → All Lab Computers       (PUT failed after retry — source not deleted)

2 succeeded, 1 skipped, 1 failed
```

**Log file:** `logs/<timestamp>.log` — full details for every merge entry including member IDs added, skipped, and any errors.

**Debug dumps:** `debug/<timestamp>_<group_id>.json` — raw API responses for troubleshooting.

---

## Code Structure

```
jamf_group_cleanup/
├── .env                  # JAMF_URL, CLIENT_ID, CLIENT_SECRET (gitignored)
├── requirements.txt      # -e ../jamf_client, pyyaml, pytest
├── run.sh                # activates venv, runs run.py "$@"
├── run.py                # entry point: arg parsing, phase orchestration
├── merge.yaml            # user's merge config (gitignored)
├── resolver.py           # Phase 1: name→ID lookup, type detection, member snapshot
├── executor.py           # Phase 3: add members, delete source, retry logic
├── reporter.py           # dry-run output, per-entry results, summary, log writing
├── logs/                 # timestamped .log files (last 8 kept)
├── debug/                # raw API JSON dumps
└── tests/
    ├── test_resolver.py
    ├── test_executor.py
    └── test_reporter.py
```

**Module responsibilities:**
- `run.py` — loads config, calls resolver, exits on validation failure or `--dry`, then calls executor, then reporter.
- `resolver.py` — all read-only API calls; returns a resolved merge plan (IDs, group kinds, member lists).
- `executor.py` — all write API calls; accepts a resolved merge plan, returns per-entry results.
- `reporter.py` — pure output: dry-run plan printing, result summary, log writing.

---

## API Endpoints Used (Jamf Classic API)

| Operation | Endpoint |
|---|---|
| List all computer groups | `GET /JSSResource/computergroups` |
| Get computer group by name | `GET /JSSResource/computergroups/name/{name}` |
| Get computer group by ID | `GET /JSSResource/computergroups/id/{id}` |
| Update computer static group | `PUT /JSSResource/computergroups/id/{id}` |
| Delete computer group | `DELETE /JSSResource/computergroups/id/{id}` |
| List all mobile device groups | `GET /JSSResource/mobiledevicegroups` |
| Get mobile device group by name | `GET /JSSResource/mobiledevicegroups/name/{name}` |
| Get mobile device group by ID | `GET /JSSResource/mobiledevicegroups/id/{id}` |
| Update mobile device static group | `PUT /JSSResource/mobiledevicegroups/id/{id}` |
| Delete mobile device group | `DELETE /JSSResource/mobiledevicegroups/id/{id}` |

Auth via bearer token from `jamf_client.get_token()`. XML request/response bodies (classic API convention).

---

## Constraints & Non-Goals

- Smart groups as targets are explicitly unsupported (rejected in validation).
- Smart group criteria are not transferred — only the snapshot of current members is added to the target.
- No rollback: if a source group is deleted and a subsequent step fails, there is no undo.
- No parallel execution: merges run sequentially to keep error handling and logging simple.
- Merge order follows YAML order.
