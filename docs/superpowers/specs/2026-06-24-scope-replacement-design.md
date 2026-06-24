# Scope Replacement Feature — Design Spec

**Date:** 2026-06-24
**Status:** Approved

---

## Overview

Extends `jamf_group_cleanup` with a `scope` subcommand. Given a source group and a target group, the tool finds all Jamf policies and configuration profiles that reference the source group in their scope (inclusions or exclusions), replaces the source group with the target group, and logs a deprecation notice for the source group. The source group is never deleted.

The existing merge functionality moves behind a `merge` subcommand. Both subcommands share `config.yaml`.

---

## CLI Structure

```sh
./run.sh merge [--dry]    # existing: add source members to target, delete source
./run.sh scope [--dry]    # new: replace source group with target in policy/profile scopes
```

`--dry` is supported on both subcommands. With `--dry`, the tool validates the config and prints a plan but makes no API writes.

---

## Config Format

`merge.yaml` is renamed to `config.yaml`. `merge.yaml.example` → `config.yaml.example`.

```yaml
merges:
  - source: "Old Staff Macs"
    target: "All Staff Computers"
    type: computer

scopes:
  - source: "Old Group"
    target: "New Group"
    type: computer         # computer or mobile_device

  - source: "Old iPad Group"
    target: "All iPads"
    type: mobile_device
```

**`scopes` entry fields:**

| Field | Required | Description |
|---|---|---|
| `source` | yes | Group name (string) or Jamf ID (integer) to replace |
| `target` | yes | Group name (string) or Jamf ID (integer) to substitute in |
| `type` | yes | `computer` or `mobile_device` |

Both `merge` and `scope` subcommands ignore whichever section doesn't apply to them — `run.sh merge` reads only `merges:`, `run.sh scope` reads only `scopes:`.

---

## Scope Pipeline

### Phase 1 — Resolution & Validation (always runs)

For each `scopes` entry:
1. Resolve source and target by name or ID via the Jamf classic API (same `_lookup_group` logic as merge).
2. Validate: both groups must exist; `type` must be `computer` or `mobile_device`; required fields (`source`, `target`, `type`) must be present.
3. Scan all relevant Jamf objects for references to the source group:
   - `type: computer` → all **computer policies** + **macOS config profiles**
   - `type: mobile_device` → all **mobile device config profiles**
   - Use the list endpoint to get all object IDs, then GET each object individually to inspect its scope XML.
4. For each scanned object, check:
   - `scope/computer_groups` (inclusions)
   - `scope/exclusions/computer_groups` (exclusions)
5. Collect every object that references the source group into a `ResolvedScope`.

All validation errors are collected before any writes. If any entry has errors, print all errors and exit.

### Phase 2 — Dry-run output (if `--dry`)

For each `ResolvedScope`, print:
- Source group name, target group name, type
- List of matching objects: name, object type (policy / macOS profile / mobile profile), whether match is in inclusions, exclusions, or both
- Objects where target group is already present (would be a no-op for that object)

Exit with code 0. No writes.

### Phase 3 — Execution (if not `--dry`)

For each matching `ScopedObject` in each `ResolvedScope`:
1. GET full XML for the object.
2. Parse XML; locate source group in inclusions and/or exclusions.
3. Replace source group element with target group element in-place.
4. PUT updated XML back.
5. On PUT failure: retry once. If retry fails: log error, mark FAIL, continue.

After all objects for an entry are processed:
- Log deprecated notice: `source group '[name]' (id=X) scope references replaced by '[target]' (id=Y) — group not deleted`
- If any object failed: mark entry as FAIL (partial).

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| Group not found | Fatal — collected with all validation errors, exit before Phase 3 |
| Invalid or missing `type`/`source`/`target` | Fatal — same |
| Source group not found in any object scope | Entry marked SKIP, logged |
| Target group already present in object scope | Skip that object (no-op), log |
| PUT fails on first attempt | Retry once |
| PUT fails on retry | Log error, mark FAIL, continue to next object |

---

## Output & Logging

**Console (dry-run):**
```
DRY RUN — no changes will be made

[1] Old Group (computer) → New Group
    computer policies:     3 would be updated
    macOS config profiles: 1 would be updated
    mobile device profiles: 0
    Already has target:    1 object (no-op)
```

**Console (execution):**
```
[OK]   Old Group → New Group  (4 objects updated)
[SKIP] Old iPad Group → All iPads  (source group not found in any scope)
[FAIL] Old Lab Group → New Lab Group  (PUT failed for policy 'Deploy Xcode' — source not deleted)

2 succeeded, 1 skipped, 0 failed
```

**Log file:** `logs/<timestamp>.log` — per-entry summary including each object updated, deprecated notice, and any errors.

---

## Data Classes

```python
# scope_resolver.py
@dataclass
class ScopedObject:
    object_id: int
    object_name: str
    object_type: str          # "policy", "osx_profile", "mobile_profile"
    in_inclusions: bool
    in_exclusions: bool

@dataclass
class ResolvedScope:
    source_id: int
    source_name: str
    target_id: int
    target_name: str
    group_type: str            # "computer" or "mobile_device"
    objects: list              # list[ScopedObject] that reference source group

# scope_executor.py
@dataclass
class ScopeResult:
    resolved: ResolvedScope
    status: str                # "OK", "SKIP", "FAIL"
    objects_updated: list      # list[ScopedObject] successfully updated
    error: str | None
```

---

## Code Structure

```
jamf_group_cleanup/
├── config.yaml              # gitignored; renamed from merge.yaml
├── config.yaml.example      # renamed from merge.yaml.example
├── scope_resolver.py        # Phase 1: lookup, scan, return ResolvedScope list
├── scope_executor.py        # Phase 3: GET/replace/PUT per object; return ScopeResult list
│
│   (modified)
├── run.py                   # argparse subcommands; dispatch merge or scope
├── reporter.py              # add scope dry-run, scope results, scope log writing
│
│   (unchanged)
├── api.py
├── resolver.py
└── executor.py
```

---

## API Endpoints Used

| Object type | List | Get / Put |
|---|---|---|
| Computer policies | `GET /JSSResource/policies` | `/JSSResource/policies/id/{id}` |
| macOS config profiles | `GET /JSSResource/osxconfigurationprofiles` | `/JSSResource/osxconfigurationprofiles/id/{id}` |
| Mobile device profiles | `GET /JSSResource/mobiledeviceconfigurationprofiles` | `/JSSResource/mobiledeviceconfigurationprofiles/id/{id}` |

Auth: bearer token via `jamf_client.get_token()`. XML request/response bodies.

---

## Constraints & Non-Goals

- Source group is never deleted by the `scope` subcommand.
- Only group-based scope entries are modified — individual computer/device inclusions and other scope criteria (buildings, departments, network segments) are untouched.
- `merge` and `scope` subcommands are independent — running one does not trigger the other.
- No rollback: if a PUT succeeds and a later object fails, already-updated objects are not reverted.
- Merges run sequentially (YAML order); scope objects within an entry also run sequentially.
