# Smart Group Scope Transfer

**Date:** 2026-06-30
**Status:** Approved

## Summary

Extend the `scope` command so that smart groups whose membership criteria reference the source group are also updated to reference the target group. Covers both computer and mobile device group types.

## Background

The existing `scope` pipeline finds policies and config profiles that have the source group in their `<scope>` XML and replaces those references with the target group. Smart groups are not currently scanned. In Jamf Pro, a smart group can use a "member of group" criterion (e.g. `<name>Computer Group</name>`, `<value>Old Staff Macs</value>`) to dynamically include devices that belong to a static group. When a source static group is being retired in favour of a target group, those smart group criteria must also be updated or devices will fall out of the smart group.

## Assumption to Verify

The criterion `<name>` field for group membership is `"Computer Group"` for computer smart groups and `"Mobile Device Group"` for mobile device smart groups. These will be stored as named constants so they can be corrected if the first dry run against a real instance reveals a different string.

## Data Model

### New dataclass — `SmartGroupCriterionRef` (scope_resolver.py)

```python
@dataclass
class SmartGroupCriterionRef:
    group_id: int
    group_name: str
    target_already_present: bool = False
```

Represents a smart group whose criteria reference the source group. `target_already_present` is `True` when at least one criterion already references the target group name, making the update a no-op.

### Updated `ResolvedScope` (scope_resolver.py)

Gains one new field with a safe default so all existing test fixtures still construct without changes:

```python
smart_groups: list = field(default_factory=list)  # List[SmartGroupCriterionRef]
```

### Updated `ScopeResult` (scope_executor.py)

Gains one new field with a safe default:

```python
smart_groups_updated: list = field(default_factory=list)  # List[SmartGroupCriterionRef]
```

Failures in the smart group loop contribute to the same `status="FAIL"` on `ScopeResult` as failures in the policy/profile loop.

## Resolver

### New constants (scope_resolver.py)

```python
SMART_GROUP_LIST_PATH = {
    "computer": "/JSSResource/computergroups",
    "mobile_device": "/JSSResource/mobiledevicegroups",
}

SMART_CRITERION_NAME = {
    "computer": "Computer Group",
    "mobile_device": "Mobile Device Group",
}
```

### New function — `_scan_smart_groups`

Signature: `_scan_smart_groups(source_name, target_name, group_type, token, session) -> list[SmartGroupCriterionRef]`

Algorithm:
1. GET `SMART_GROUP_LIST_PATH[group_type]`. On failure, print a warning to stderr and return `[]`. On success, filter to smart groups: the list XML includes `<is_smart>` per item; if absent from list items, fall back to reading it from each detail fetch (same request, no extra cost).
2. For each smart group ID, GET detail XML.
3. Walk `criteria/criterion` elements:
   - If `<name>` == `SMART_CRITERION_NAME[group_type]` AND `<value>` == `source_name` → match found.
   - If `<name>` == `SMART_CRITERION_NAME[group_type]` AND `<value>` == `target_name` → set `target_already_present = True`.
4. Append a `SmartGroupCriterionRef` for each matching smart group.

Called at the end of `resolve_scope`, after the existing `_scan_object_type` loop. Results stored in `resolved.smart_groups`.

## Executor

### New constants (scope_executor.py)

```python
SMART_GROUP_PUT_PATH = {
    "computer": "/JSSResource/computergroups/id/{}",
    "mobile_device": "/JSSResource/mobiledevicegroups/id/{}",
}
```

### New helper — `_replace_criterion_value`

Signature: `_replace_criterion_value(xml_text, criterion_name, source_name, target_name) -> str`

Walks all `criteria/criterion` elements and replaces `<value>` with `target_name` wherever `<name>` == `criterion_name` AND `<value>` == `source_name`. Replaces all matches (a smart group may reference the same group multiple times with different `and_or` or `search_type`). Returns the serialised XML string.

### Updated `execute_scope`

After the existing policy/profile loop, a second loop iterates `rs.smart_groups`. For each `SmartGroupCriterionRef` where `not target_already_present`:

1. GET fresh XML — re-verify the source criterion is still present by checking whether any `criteria/criterion` element has `<name>` == `SMART_CRITERION_NAME[group_type]` AND `<value>` == `source_name`.
2. If no such criterion exists, skip (no-op — another admin already updated it).
3. `_replace_criterion_value` on fresh XML.
4. `put_with_retry` to `SMART_GROUP_PUT_PATH[rs.group_type].format(sg.group_id)`.
5. On PUT failure: re-GET and check whether any criterion still references `source_name`. If none do, the change applied despite the error (log warning, mark updated). Otherwise, mark as failed.
6. On success: append to `smart_groups_updated`.

Errors accumulate in `fail_errors`; the `ScopeResult.status` is `"FAIL"` if any error occurs in either loop.

## Reporter

`print_scope_dry_run` adds a section after the existing objects list when `resolved.smart_groups` is non-empty:

```
Smart groups whose criteria will be updated:
  - My Smart Group  [already references target, will skip]
  - Another Smart Group
```

`print_scope_results` adds a line showing smart groups updated/skipped when `result.smart_groups_updated` is non-empty or when smart groups were present in the resolved scope. Section is omitted when no smart groups were found.

## Tests

New file: `tests/test_smart_group_scope.py`

Covers `_scan_smart_groups`:
- Finds a smart group with a matching criterion.
- Ignores static groups (`is_smart=false`).
- Ignores criteria with a non-matching `<name>`.
- Sets `target_already_present=True` when target criterion already exists.
- Skips on list GET failure (warns, returns empty).

Covers `_replace_criterion_value`:
- Replaces a single matching criterion.
- Replaces all matching criteria when multiple exist.
- Leaves non-matching criteria untouched.

Covers `execute_scope` with smart groups:
- OK path — smart group updated and added to `smart_groups_updated`.
- Skip when `target_already_present`.
- PUT failure with verify-GET showing change applied → `OK` with warning.
- PUT failure with verify-GET showing source still present → `FAIL`.
- Continues processing remaining smart groups after a failure.

Existing tests are unaffected — the new `smart_groups` and `smart_groups_updated` fields default to `[]`.
