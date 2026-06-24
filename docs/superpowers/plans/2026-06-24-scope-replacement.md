# Scope Replacement Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `scope` subcommand that replaces a source group with a target group across all Jamf policy and config profile scopes, and move existing merge functionality behind a `merge` subcommand.

**Architecture:** Two new modules (`scope_resolver.py`, `scope_executor.py`) follow the resolver→executor→reporter pipeline pattern already established by the merge flow. `run.py` is refactored to argparse subcommands; `reporter.py` gains scope-specific output functions. Config file is renamed from `merge.yaml` to `config.yaml`.

**Tech Stack:** Python 3.11+, `xml.etree.ElementTree`, `pyyaml`, `requests`, `pytest`, `unittest.mock`; Jamf Pro Classic API (XML over HTTPS, bearer token auth via `jamf_client`)

## Global Constraints

- Python 3.11+; no new third-party dependencies beyond existing `requirements.txt`
- All Jamf API calls go through `api.py` helpers: `classic_get`, `classic_put`, `classic_delete`
- Bearer token lifecycle: `get_token()` before try-block, `invalidate_token()` in finally-block
- Config file: `config.yaml` (renamed from `merge.yaml`); gitignored; `config.yaml.example` is the template
- `--dry` on both subcommands: validates + prints plan, zero API writes, exit 0
- Collect ALL validation errors before any writes; print all errors and exit 1 if any
- Retry-once on PUT failure; continue to next object on second failure
- Source group is **never** deleted by the `scope` subcommand
- Sequential execution (YAML order); no rollback on partial failure

---

### Task 1: Config rename + run.py subcommands

**Files:**
- Rename: `merge.yaml.example` → `config.yaml.example`
- Modify: `run.py` (full rewrite of CLI + dispatch; merge logic unchanged)

**Interfaces:**
- Produces: `run.py` with `merge` and `scope` subcommands; `_cmd_merge(args)` and `_cmd_scope(args)` dispatch functions; `_load_config()` helper reading `config.yaml`

- [ ] **Step 1: Rename the example config**

```bash
git mv merge.yaml.example config.yaml.example
```

Open `config.yaml.example` and add a `scopes:` section after `merges:`:

```yaml
merges:
  # Merge a static computer group (by name) into another static computer group
  - source: "Old Staff Macs"
    target: "All Staff Computers"
    type: computer

  # Use a Jamf ID instead of a name (useful when names contain special characters)
  - source: 4821
    target: "All Student iPads"
    type: mobile_device

  # Smart groups are supported as source — members are snapshotted at run time
  - source: "Retired iPad Smart Group"
    target: "All Student iPads"
    type: mobile_device

scopes:
  # Replace source group with target in all policy/profile scopes (computers)
  - source: "Old Staff Macs"
    target: "All Staff Computers"
    type: computer

  # Replace source group in mobile device profile scopes
  - source: "Old iPad Group"
    target: "All Student iPads"
    type: mobile_device
```

- [ ] **Step 2: Rewrite run.py with subcommands**

```python
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
from reporter import print_dry_run, print_results, write_log
from resolver import resolve


def _load_config():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    if not os.path.exists(config_path):
        print("config.yaml not found. Copy config.yaml.example to config.yaml and fill it in.", file=sys.stderr)
        sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def _cmd_merge(args):
    config = _load_config()
    entries = config.get("merges", [])
    if not entries:
        print("No merges defined in config.yaml.", file=sys.stderr)
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

        if any(r.status == "FAIL" for r in results):
            sys.exit(1)
    finally:
        invalidate_token(access_token)


def _cmd_scope(args):
    print("scope subcommand not yet implemented", file=sys.stderr)
    sys.exit(1)


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
```

- [ ] **Step 3: Verify existing tests still pass**

```bash
pytest -v
```

Expected: all existing tests pass (34 tests). The argparse refactor does not touch `resolver.py`, `executor.py`, or `reporter.py`.

- [ ] **Step 4: Commit**

```bash
git add config.yaml.example run.py
git commit -m "feat: rename config to config.yaml, add merge/scope argparse subcommands"
```

---

### Task 2: scope_resolver.py — data classes and XML helpers

**Files:**
- Create: `scope_resolver.py`
- Create: `tests/test_scope_resolver.py`

**Interfaces:**
- Produces:
  - `ScopedObject(object_id, object_name, object_type, in_inclusions, in_exclusions, target_already_present)`
  - `ResolvedScope(source_id, source_name, target_id, target_name, group_type, objects)`
  - `OBJECT_TYPE_SPECS: dict` — maps `group_type` to list of spec dicts
  - `_parse_ids_from_list_xml(xml_text: str, item_tag: str) -> list[int]`
  - `_check_object_for_group(xml_text: str, source_id: int, target_id: int, include_path: str, exclude_path: str) -> tuple[bool, bool, bool]` — `(in_inclusions, in_exclusions, target_already_present)`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scope_resolver.py`:

```python
import xml.etree.ElementTree as ET
from scope_resolver import (
    ScopedObject, ResolvedScope,
    _parse_ids_from_list_xml, _check_object_for_group,
)

POLICY_LIST_XML = """<?xml version="1.0" encoding="UTF-8"?>
<policies>
    <size>2</size>
    <policy><id>10</id><name>Deploy Software</name></policy>
    <policy><id>11</id><name>Run Script</name></policy>
</policies>"""

EMPTY_LIST_XML = """<?xml version="1.0" encoding="UTF-8"?>
<policies><size>0</size></policies>"""

INCLUDE_PATH = "scope/computer_groups/computer_group"
EXCLUDE_PATH = "scope/exclusions/computer_groups/computer_group"

POLICY_SOURCE_IN_INCLUSION = """<?xml version="1.0" encoding="UTF-8"?>
<policy>
    <general><id>10</id><name>Deploy Software</name></general>
    <scope>
        <computer_groups>
            <computer_group><id>1</id><name>Old Group</name></computer_group>
        </computer_groups>
        <exclusions><computer_groups/></exclusions>
    </scope>
</policy>"""

POLICY_SOURCE_IN_EXCLUSION = """<?xml version="1.0" encoding="UTF-8"?>
<policy>
    <general><id>10</id><name>Deploy Software</name></general>
    <scope>
        <computer_groups/>
        <exclusions>
            <computer_groups>
                <computer_group><id>1</id><name>Old Group</name></computer_group>
            </computer_groups>
        </exclusions>
    </scope>
</policy>"""

POLICY_SOURCE_IN_BOTH = """<?xml version="1.0" encoding="UTF-8"?>
<policy>
    <general><id>10</id><name>Deploy Software</name></general>
    <scope>
        <computer_groups>
            <computer_group><id>1</id><name>Old Group</name></computer_group>
        </computer_groups>
        <exclusions>
            <computer_groups>
                <computer_group><id>1</id><name>Old Group</name></computer_group>
            </computer_groups>
        </exclusions>
    </scope>
</policy>"""

POLICY_TARGET_ALREADY_PRESENT = """<?xml version="1.0" encoding="UTF-8"?>
<policy>
    <general><id>10</id><name>Deploy Software</name></general>
    <scope>
        <computer_groups>
            <computer_group><id>1</id><name>Old Group</name></computer_group>
            <computer_group><id>2</id><name>New Group</name></computer_group>
        </computer_groups>
        <exclusions><computer_groups/></exclusions>
    </scope>
</policy>"""

POLICY_NO_SOURCE = """<?xml version="1.0" encoding="UTF-8"?>
<policy>
    <general><id>11</id><name>Run Script</name></general>
    <scope>
        <computer_groups/>
        <exclusions><computer_groups/></exclusions>
    </scope>
</policy>"""


# ── _parse_ids_from_list_xml ─────────────────────────────────────────────────

def test_parse_ids_returns_list():
    ids = _parse_ids_from_list_xml(POLICY_LIST_XML, "policy")
    assert ids == [10, 11]

def test_parse_ids_empty_list():
    ids = _parse_ids_from_list_xml(EMPTY_LIST_XML, "policy")
    assert ids == []


# ── _check_object_for_group ──────────────────────────────────────────────────

def test_check_source_in_inclusion():
    inc, exc, already = _check_object_for_group(
        POLICY_SOURCE_IN_INCLUSION, 1, 2, INCLUDE_PATH, EXCLUDE_PATH
    )
    assert inc is True
    assert exc is False
    assert already is False

def test_check_source_in_exclusion():
    inc, exc, already = _check_object_for_group(
        POLICY_SOURCE_IN_EXCLUSION, 1, 2, INCLUDE_PATH, EXCLUDE_PATH
    )
    assert inc is False
    assert exc is True
    assert already is False

def test_check_source_in_both():
    inc, exc, already = _check_object_for_group(
        POLICY_SOURCE_IN_BOTH, 1, 2, INCLUDE_PATH, EXCLUDE_PATH
    )
    assert inc is True
    assert exc is True
    assert already is False

def test_check_target_already_present():
    inc, exc, already = _check_object_for_group(
        POLICY_TARGET_ALREADY_PRESENT, 1, 2, INCLUDE_PATH, EXCLUDE_PATH
    )
    assert inc is True
    assert already is True

def test_check_source_not_present():
    inc, exc, already = _check_object_for_group(
        POLICY_NO_SOURCE, 99, 2, INCLUDE_PATH, EXCLUDE_PATH
    )
    assert inc is False
    assert exc is False
    assert already is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_scope_resolver.py -v
```

Expected: `ModuleNotFoundError: No module named 'scope_resolver'`

- [ ] **Step 3: Implement scope_resolver.py (data classes + helpers only)**

Create `scope_resolver.py`:

```python
from dataclasses import dataclass, field
import xml.etree.ElementTree as ET
from urllib.parse import quote
from api import classic_get
from resolver import _lookup_group, ValidationError


@dataclass
class ScopedObject:
    object_id: int
    object_name: str
    object_type: str          # "policy", "osx_profile", "mobile_profile"
    in_inclusions: bool
    in_exclusions: bool
    target_already_present: bool = False


@dataclass
class ResolvedScope:
    source_id: int
    source_name: str
    target_id: int
    target_name: str
    group_type: str            # "computer" or "mobile_device"
    objects: list = field(default_factory=list)


OBJECT_TYPE_SPECS = {
    "computer": [
        {
            "object_type": "policy",
            "list_path": "/JSSResource/policies",
            "list_tag": "policy",
            "detail_template": "/JSSResource/policies/id/{}",
            "include_path": "scope/computer_groups/computer_group",
            "exclude_path": "scope/exclusions/computer_groups/computer_group",
        },
        {
            "object_type": "osx_profile",
            "list_path": "/JSSResource/osxconfigurationprofiles",
            "list_tag": "os_x_configuration_profile",
            "detail_template": "/JSSResource/osxconfigurationprofiles/id/{}",
            "include_path": "scope/computer_groups/computer_group",
            "exclude_path": "scope/exclusions/computer_groups/computer_group",
        },
    ],
    "mobile_device": [
        {
            "object_type": "mobile_profile",
            "list_path": "/JSSResource/mobiledeviceconfigurationprofiles",
            "list_tag": "configuration_profile",
            "detail_template": "/JSSResource/mobiledeviceconfigurationprofiles/id/{}",
            "include_path": "scope/mobile_device_groups/mobile_device_group",
            "exclude_path": "scope/exclusions/mobile_device_groups/mobile_device_group",
        },
    ],
}


def _parse_ids_from_list_xml(xml_text, item_tag):
    root = ET.fromstring(xml_text)
    return [int(el.findtext("id")) for el in root.findall(item_tag)]


def _check_object_for_group(xml_text, source_id, target_id, include_path, exclude_path):
    root = ET.fromstring(xml_text)
    in_inc = False
    in_exc = False
    target_present = False

    for el in root.findall(include_path):
        gid = int(el.findtext("id") or 0)
        if gid == source_id:
            in_inc = True
        if gid == target_id:
            target_present = True

    for el in root.findall(exclude_path):
        gid = int(el.findtext("id") or 0)
        if gid == source_id:
            in_exc = True
        if gid == target_id:
            target_present = True

    return in_inc, in_exc, target_present
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_scope_resolver.py -v
```

Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scope_resolver.py tests/test_scope_resolver.py
git commit -m "feat: scope_resolver data classes and XML helpers"
```

---

### Task 3: scope_resolver.py — resolve_scope()

**Files:**
- Modify: `scope_resolver.py` (add `_scan_object_type` and `resolve_scope`)
- Modify: `tests/test_scope_resolver.py` (add resolve tests)

**Interfaces:**
- Consumes: `ScopedObject`, `ResolvedScope`, `OBJECT_TYPE_SPECS`, `_parse_ids_from_list_xml`, `_check_object_for_group` (from Task 2); `_lookup_group`, `ValidationError` (from `resolver.py`)
- Produces:
  - `_scan_object_type(spec: dict, source_id: int, target_id: int, token: dict, session) -> list[ScopedObject]`
  - `resolve_scope(entries: list, token: dict, session) -> tuple[list[ResolvedScope], list[ValidationError]]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scope_resolver.py`:

```python
from unittest.mock import MagicMock, patch
from scope_resolver import resolve_scope

SOURCE_GROUP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<computer_group>
    <id>1</id><name>Old Group</name><is_smart>false</is_smart><computers/>
</computer_group>"""

TARGET_GROUP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<computer_group>
    <id>2</id><name>New Group</name><is_smart>false</is_smart><computers/>
</computer_group>"""

OSX_PROFILE_LIST_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<os_x_configuration_profiles><size>0</size></os_x_configuration_profiles>"""


def _mock_response(status_code, text=""):
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    r.ok = status_code < 400
    r.raise_for_status = MagicMock()
    return r


def _make_token():
    return {"t": "tok", "expiration": 9999999999}


def test_resolve_scope_finds_matching_object():
    entries = [{"source": "Old Group", "target": "New Group", "type": "computer"}]

    with patch("scope_resolver.classic_get") as mock_get:
        mock_get.side_effect = [
            _mock_response(200, SOURCE_GROUP_XML),        # lookup source
            _mock_response(200, TARGET_GROUP_XML),        # lookup target
            _mock_response(200, POLICY_LIST_XML),         # list policies
            _mock_response(200, POLICY_SOURCE_IN_INCLUSION),  # policy 10 detail
            _mock_response(200, POLICY_NO_SOURCE),        # policy 11 detail
            _mock_response(200, OSX_PROFILE_LIST_EMPTY),  # list osx profiles
        ]
        resolved, errors = resolve_scope(entries, _make_token(), MagicMock())

    assert errors == []
    assert len(resolved) == 1
    rs = resolved[0]
    assert rs.source_id == 1
    assert rs.source_name == "Old Group"
    assert rs.target_id == 2
    assert rs.target_name == "New Group"
    assert rs.group_type == "computer"
    assert len(rs.objects) == 1
    assert rs.objects[0].object_id == 10
    assert rs.objects[0].object_type == "policy"
    assert rs.objects[0].in_inclusions is True
    assert rs.objects[0].in_exclusions is False


def test_resolve_scope_source_not_found():
    entries = [{"source": "Ghost Group", "target": "New Group", "type": "computer"}]

    with patch("scope_resolver.classic_get") as mock_get:
        mock_get.side_effect = [
            _mock_response(404),                   # lookup source → not found
            _mock_response(200, TARGET_GROUP_XML), # lookup target
        ]
        resolved, errors = resolve_scope(entries, _make_token(), MagicMock())

    assert len(errors) == 1
    assert "Ghost Group" in errors[0].message
    assert resolved == []


def test_resolve_scope_invalid_type():
    entries = [{"source": "Old Group", "target": "New Group", "type": "tablet"}]
    resolved, errors = resolve_scope(entries, _make_token(), MagicMock())
    assert len(errors) == 1
    assert "tablet" in errors[0].message


def test_resolve_scope_missing_fields():
    entries = [{"source": "Old Group"}]
    resolved, errors = resolve_scope(entries, _make_token(), MagicMock())
    assert len(errors) == 1
    assert "target" in errors[0].message or "type" in errors[0].message


def test_resolve_scope_no_matching_objects():
    entries = [{"source": "Old Group", "target": "New Group", "type": "computer"}]

    with patch("scope_resolver.classic_get") as mock_get:
        mock_get.side_effect = [
            _mock_response(200, SOURCE_GROUP_XML),
            _mock_response(200, TARGET_GROUP_XML),
            _mock_response(200, POLICY_LIST_XML),
            _mock_response(200, POLICY_NO_SOURCE),    # policy 10: no source
            _mock_response(200, POLICY_NO_SOURCE),    # policy 11: no source
            _mock_response(200, OSX_PROFILE_LIST_EMPTY),
        ]
        resolved, errors = resolve_scope(entries, _make_token(), MagicMock())

    assert errors == []
    assert len(resolved) == 1
    assert resolved[0].objects == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_scope_resolver.py::test_resolve_scope_finds_matching_object -v
```

Expected: `ImportError` or `AttributeError` — `resolve_scope` not defined yet.

- [ ] **Step 3: Implement `_scan_object_type` and `resolve_scope`**

Append to `scope_resolver.py`:

```python
def _scan_object_type(spec, source_id, target_id, token, session):
    list_response = classic_get(spec["list_path"], token, session)
    list_response.raise_for_status()
    ids = _parse_ids_from_list_xml(list_response.text, spec["list_tag"])

    objects = []
    for obj_id in ids:
        detail_path = spec["detail_template"].format(obj_id)
        detail_response = classic_get(detail_path, token, session)
        if not detail_response.ok:
            continue

        in_inc, in_exc, target_present = _check_object_for_group(
            detail_response.text, source_id, target_id,
            spec["include_path"], spec["exclude_path"],
        )

        if not in_inc and not in_exc:
            continue

        root = ET.fromstring(detail_response.text)
        obj_name = root.findtext("general/name") or root.findtext("name") or ""

        objects.append(ScopedObject(
            object_id=obj_id,
            object_name=obj_name,
            object_type=spec["object_type"],
            in_inclusions=in_inc,
            in_exclusions=in_exc,
            target_already_present=target_present,
        ))

    return objects


def resolve_scope(entries, token, session):
    resolved = []
    errors = []

    for i, entry in enumerate(entries):
        source_ref = entry.get("source")
        target_ref = entry.get("target")
        group_type = entry.get("type", "")
        missing = [k for k, v in [("source", source_ref), ("target", target_ref), ("type", group_type or None)] if v is None]
        if missing:
            errors.append(ValidationError(i, f"missing required fields: {', '.join(missing)}"))
            continue

        if group_type not in ("computer", "mobile_device"):
            errors.append(ValidationError(i, f"type '{group_type}' is invalid — must be 'computer' or 'mobile_device'"))
            continue

        source = _lookup_group(source_ref, group_type, token, session)
        target = _lookup_group(target_ref, group_type, token, session)

        entry_errors = []
        if source is None:
            entry_errors.append(ValidationError(i, f"source '{source_ref}' not found"))
        if target is None:
            entry_errors.append(ValidationError(i, f"target '{target_ref}' not found"))
        if entry_errors:
            errors.extend(entry_errors)
            continue

        if source["id"] == target["id"]:
            errors.append(ValidationError(i, f"source and target are the same group (id={source['id']})"))
            continue

        all_objects = []
        for spec in OBJECT_TYPE_SPECS[group_type]:
            all_objects.extend(_scan_object_type(spec, source["id"], target["id"], token, session))

        resolved.append(ResolvedScope(
            source_id=source["id"],
            source_name=source["name"],
            target_id=target["id"],
            target_name=target["name"],
            group_type=group_type,
            objects=all_objects,
        ))

    return resolved, errors
```

- [ ] **Step 4: Run all scope_resolver tests**

```bash
pytest tests/test_scope_resolver.py -v
```

Expected: all 12 tests pass.

- [ ] **Step 5: Run full suite**

```bash
pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add scope_resolver.py tests/test_scope_resolver.py
git commit -m "feat: scope_resolver resolve_scope() with full scan and validation"
```

---

### Task 4: scope_executor.py

**Files:**
- Create: `scope_executor.py`
- Create: `tests/test_scope_executor.py`

**Interfaces:**
- Consumes: `ResolvedScope`, `ScopedObject` from `scope_resolver`; `classic_get`, `classic_put` from `api`
- Produces:
  - `ScopeResult(resolved, status, objects_updated, error)`
  - `_replace_group_in_xml(xml_text, source_id, target_id, target_name, include_path, exclude_path, in_inclusions, in_exclusions) -> str`
  - `execute_scope(resolved_scopes, token, session) -> list[ScopeResult]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scope_executor.py`:

```python
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch
import scope_executor
from scope_executor import ScopeResult, _replace_group_in_xml
from scope_resolver import ResolvedScope, ScopedObject

INCLUDE_PATH = "scope/computer_groups/computer_group"
EXCLUDE_PATH = "scope/exclusions/computer_groups/computer_group"

POLICY_XML = """<?xml version="1.0" encoding="UTF-8"?>
<policy>
    <general><id>10</id><name>Deploy Software</name></general>
    <scope>
        <computer_groups>
            <computer_group><id>1</id><name>Old Group</name></computer_group>
        </computer_groups>
        <exclusions><computer_groups/></exclusions>
    </scope>
</policy>"""

POLICY_XML_EXCL = """<?xml version="1.0" encoding="UTF-8"?>
<policy>
    <general><id>10</id><name>Deploy Software</name></general>
    <scope>
        <computer_groups/>
        <exclusions>
            <computer_groups>
                <computer_group><id>1</id><name>Old Group</name></computer_group>
            </computer_groups>
        </exclusions>
    </scope>
</policy>"""


def _mock_response(status_code, text=""):
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    r.ok = status_code < 400
    return r


def _make_token():
    return {"t": "tok", "expiration": 9999999999}


def _make_rs(objects):
    return ResolvedScope(
        source_id=1, source_name="Old Group",
        target_id=2, target_name="New Group",
        group_type="computer",
        objects=objects,
    )


def _make_obj(in_inc=True, in_exc=False, already=False):
    return ScopedObject(
        object_id=10, object_name="Deploy Software", object_type="policy",
        in_inclusions=in_inc, in_exclusions=in_exc, target_already_present=already,
    )


# ── _replace_group_in_xml ────────────────────────────────────────────────────

def test_replace_in_inclusion():
    result = _replace_group_in_xml(
        POLICY_XML, 1, 2, "New Group",
        INCLUDE_PATH, EXCLUDE_PATH, in_inclusions=True, in_exclusions=False
    )
    root = ET.fromstring(result)
    groups = root.findall(INCLUDE_PATH)
    assert len(groups) == 1
    assert groups[0].findtext("id") == "2"
    assert groups[0].findtext("name") == "New Group"


def test_replace_in_exclusion():
    result = _replace_group_in_xml(
        POLICY_XML_EXCL, 1, 2, "New Group",
        INCLUDE_PATH, EXCLUDE_PATH, in_inclusions=False, in_exclusions=True
    )
    root = ET.fromstring(result)
    groups = root.findall(EXCLUDE_PATH)
    assert len(groups) == 1
    assert groups[0].findtext("id") == "2"
    assert groups[0].findtext("name") == "New Group"


def test_replace_preserves_other_elements():
    result = _replace_group_in_xml(
        POLICY_XML, 1, 2, "New Group",
        INCLUDE_PATH, EXCLUDE_PATH, in_inclusions=True, in_exclusions=False
    )
    root = ET.fromstring(result)
    assert root.findtext("general/name") == "Deploy Software"


# ── execute_scope ─────────────────────────────────────────────────────────────

def test_execute_scope_ok():
    rs = _make_rs([_make_obj()])
    with patch("scope_executor.classic_get", return_value=_mock_response(200, POLICY_XML)), \
         patch("scope_executor.classic_put", return_value=_mock_response(201)):
        results = scope_executor.execute_scope([rs], _make_token(), MagicMock())

    assert results[0].status == "OK"
    assert len(results[0].objects_updated) == 1
    assert results[0].objects_updated[0].object_id == 10


def test_execute_scope_skip_no_objects():
    rs = _make_rs([])
    results = scope_executor.execute_scope([rs], _make_token(), MagicMock())
    assert results[0].status == "SKIP"


def test_execute_scope_skip_target_already_present():
    rs = _make_rs([_make_obj(already=True)])
    with patch("scope_executor.classic_put") as mock_put:
        results = scope_executor.execute_scope([rs], _make_token(), MagicMock())
    mock_put.assert_not_called()
    assert results[0].status == "SKIP"


def test_execute_scope_fail_retries_put():
    rs = _make_rs([_make_obj()])
    with patch("scope_executor.classic_get", return_value=_mock_response(200, POLICY_XML)), \
         patch("scope_executor.classic_put", return_value=_mock_response(500, "err")) as mock_put:
        results = scope_executor.execute_scope([rs], _make_token(), MagicMock())

    assert results[0].status == "FAIL"
    assert mock_put.call_count == 2


def test_execute_scope_continues_after_fail():
    obj1 = ScopedObject(object_id=10, object_name="P1", object_type="policy",
                        in_inclusions=True, in_exclusions=False)
    obj2 = ScopedObject(object_id=11, object_name="P2", object_type="policy",
                        in_inclusions=True, in_exclusions=False)
    rs = _make_rs([obj1, obj2])

    get_responses = [_mock_response(200, POLICY_XML), _mock_response(200, POLICY_XML)]
    put_responses = [_mock_response(500), _mock_response(500), _mock_response(201)]

    with patch("scope_executor.classic_get", side_effect=get_responses), \
         patch("scope_executor.classic_put", side_effect=put_responses):
        results = scope_executor.execute_scope([rs], _make_token(), MagicMock())

    assert results[0].status == "FAIL"
    assert len(results[0].objects_updated) == 1
    assert results[0].objects_updated[0].object_id == 11
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_scope_executor.py -v
```

Expected: `ModuleNotFoundError: No module named 'scope_executor'`

- [ ] **Step 3: Implement scope_executor.py**

Create `scope_executor.py`:

```python
from dataclasses import dataclass, field
import xml.etree.ElementTree as ET
from api import classic_get, classic_put
from scope_resolver import ResolvedScope, ScopedObject


@dataclass
class ScopeResult:
    resolved: object
    status: str
    objects_updated: list = field(default_factory=list)
    error: str | None = None


DETAIL_PATH_BY_TYPE = {
    "policy": "/JSSResource/policies/id/{}",
    "osx_profile": "/JSSResource/osxconfigurationprofiles/id/{}",
    "mobile_profile": "/JSSResource/mobiledeviceconfigurationprofiles/id/{}",
}

INCLUDE_PATH_BY_GROUP_TYPE = {
    "computer": "scope/computer_groups/computer_group",
    "mobile_device": "scope/mobile_device_groups/mobile_device_group",
}

EXCLUDE_PATH_BY_GROUP_TYPE = {
    "computer": "scope/exclusions/computer_groups/computer_group",
    "mobile_device": "scope/exclusions/mobile_device_groups/mobile_device_group",
}


def _replace_group_in_xml(xml_text, source_id, target_id, target_name, include_path, exclude_path, in_inclusions, in_exclusions):
    root = ET.fromstring(xml_text)

    if in_inclusions:
        for el in root.findall(include_path):
            if int(el.findtext("id") or 0) == source_id:
                el.find("id").text = str(target_id)
                el.find("name").text = target_name
                break

    if in_exclusions:
        for el in root.findall(exclude_path):
            if int(el.findtext("id") or 0) == source_id:
                el.find("id").text = str(target_id)
                el.find("name").text = target_name
                break

    return ET.tostring(root, encoding="unicode")


def execute_scope(resolved_scopes, token, session):
    results = []
    for rs in resolved_scopes:
        actionable = [obj for obj in rs.objects if not obj.target_already_present]
        if not actionable:
            results.append(ScopeResult(resolved=rs, status="SKIP"))
            continue

        include_path = INCLUDE_PATH_BY_GROUP_TYPE[rs.group_type]
        exclude_path = EXCLUDE_PATH_BY_GROUP_TYPE[rs.group_type]
        objects_updated = []
        failed = False
        fail_error = None

        for obj in actionable:
            put_path = DETAIL_PATH_BY_TYPE[obj.object_type].format(obj.object_id)

            get_response = classic_get(put_path, token, session)
            if not get_response.ok:
                failed = True
                fail_error = f"GET '{obj.object_name}' {get_response.status_code}: {get_response.text[:200]}"
                continue

            updated_xml = _replace_group_in_xml(
                get_response.text, rs.source_id, rs.target_id, rs.target_name,
                include_path, exclude_path, obj.in_inclusions, obj.in_exclusions,
            )

            put_response = None
            for _ in range(2):
                put_response = classic_put(put_path, updated_xml, token, session)
                if put_response.ok:
                    break

            if not put_response.ok:
                failed = True
                fail_error = f"PUT '{obj.object_name}' {put_response.status_code}: {put_response.text[:200]}"
            else:
                objects_updated.append(obj)

        if failed:
            results.append(ScopeResult(
                resolved=rs, status="FAIL",
                objects_updated=objects_updated, error=fail_error,
            ))
        else:
            results.append(ScopeResult(resolved=rs, status="OK", objects_updated=objects_updated))

    return results
```

- [ ] **Step 4: Run all scope_executor tests**

```bash
pytest tests/test_scope_executor.py -v
```

Expected: all 8 tests pass.

- [ ] **Step 5: Run full suite**

```bash
pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add scope_executor.py tests/test_scope_executor.py
git commit -m "feat: scope_executor with replace/PUT logic and retry"
```

---

### Task 5: reporter.py — scope output functions

**Files:**
- Modify: `reporter.py` (add 3 scope functions)
- Modify: `tests/test_reporter.py` (add scope tests)

**Interfaces:**
- Consumes: `ScopeResult` from `scope_executor`; `ResolvedScope`, `ScopedObject` from `scope_resolver`
- Produces:
  - `print_scope_dry_run(resolved_scopes: list[ResolvedScope]) -> None`
  - `print_scope_results(results: list[ScopeResult]) -> None`
  - `write_scope_log(results: list[ScopeResult], log_path: str) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_reporter.py` (or create it if it doesn't exist):

```python
import os
import io
import pytest
from unittest.mock import patch
from reporter import print_scope_dry_run, print_scope_results, write_scope_log
from scope_resolver import ResolvedScope, ScopedObject
from scope_executor import ScopeResult


def _make_rs(objects=None):
    return ResolvedScope(
        source_id=1, source_name="Old Group",
        target_id=2, target_name="New Group",
        group_type="computer",
        objects=objects or [],
    )


def _make_obj(object_type="policy", already=False):
    return ScopedObject(
        object_id=10, object_name="Deploy Software",
        object_type=object_type, in_inclusions=True, in_exclusions=False,
        target_already_present=already,
    )


# ── print_scope_dry_run ───────────────────────────────────────────────────────

def test_dry_run_shows_header(capsys):
    print_scope_dry_run([])
    out = capsys.readouterr().out
    assert "DRY RUN" in out


def test_dry_run_counts_by_type(capsys):
    policy_obj = _make_obj("policy")
    profile_obj = _make_obj("osx_profile")
    rs = _make_rs([policy_obj, profile_obj])
    print_scope_dry_run([rs])
    out = capsys.readouterr().out
    assert "Old Group" in out
    assert "New Group" in out
    assert "1" in out  # count appears


def test_dry_run_shows_already_has_target(capsys):
    rs = _make_rs([_make_obj(already=True)])
    print_scope_dry_run([rs])
    out = capsys.readouterr().out
    assert "Already has target" in out or "no-op" in out


# ── print_scope_results ───────────────────────────────────────────────────────

def test_scope_results_ok(capsys):
    obj = _make_obj()
    rs = _make_rs([obj])
    result = ScopeResult(resolved=rs, status="OK", objects_updated=[obj])
    print_scope_results([result])
    out = capsys.readouterr().out
    assert "[OK]" in out
    assert "Old Group" in out
    assert "1 object" in out or "1" in out


def test_scope_results_skip(capsys):
    rs = _make_rs([])
    result = ScopeResult(resolved=rs, status="SKIP")
    print_scope_results([result])
    out = capsys.readouterr().out
    assert "[SKIP]" in out


def test_scope_results_fail(capsys):
    rs = _make_rs([_make_obj()])
    result = ScopeResult(resolved=rs, status="FAIL", error="PUT 500: error")
    print_scope_results([result])
    out = capsys.readouterr().out
    assert "[FAIL]" in out
    assert "PUT 500" in out


def test_scope_results_summary(capsys):
    rs = _make_rs()
    results = [
        ScopeResult(resolved=rs, status="OK", objects_updated=[]),
        ScopeResult(resolved=rs, status="SKIP"),
        ScopeResult(resolved=rs, status="FAIL", error="err"),
    ]
    print_scope_results(results)
    out = capsys.readouterr().out
    assert "1 succeeded" in out
    assert "1 skipped" in out
    assert "1 failed" in out


# ── write_scope_log ───────────────────────────────────────────────────────────

def test_write_scope_log_creates_file(tmp_path):
    obj = _make_obj()
    rs = _make_rs([obj])
    result = ScopeResult(resolved=rs, status="OK", objects_updated=[obj])
    log_path = str(tmp_path / "test.log")
    write_scope_log([result], log_path)
    content = open(log_path).read()
    assert "OK" in content
    assert "Old Group" in content
    assert "Deploy Software" in content
    assert "DEPRECATED" in content


def test_write_scope_log_skip_no_deprecated(tmp_path):
    rs = _make_rs([])
    result = ScopeResult(resolved=rs, status="SKIP")
    log_path = str(tmp_path / "test.log")
    write_scope_log([result], log_path)
    content = open(log_path).read()
    assert "DEPRECATED" not in content
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_reporter.py -k "scope" -v
```

Expected: `ImportError` — scope functions not defined yet.

- [ ] **Step 3: Implement scope reporter functions**

Append to `reporter.py`:

```python
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
            if r.status != "SKIP":
                f.write(f"  DEPRECATED: '{rs.source_name}' (id={rs.source_id}) scope references replaced by '{rs.target_name}' (id={rs.target_id}) — group not deleted\n")
            if r.error:
                f.write(f"  error={r.error}\n")
```

- [ ] **Step 4: Run scope reporter tests**

```bash
pytest tests/test_reporter.py -v
```

Expected: all reporter tests pass.

- [ ] **Step 5: Run full suite**

```bash
pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add reporter.py tests/test_reporter.py
git commit -m "feat: reporter scope dry-run, results, and log functions"
```

---

### Task 6: Wire up run.py + README update

**Files:**
- Modify: `run.py` (wire `_cmd_scope` with real pipeline)
- Modify: `README.md` (add scope subcommand docs; update config filename; update merge usage)

**Interfaces:**
- Consumes: `resolve_scope` from `scope_resolver`; `execute_scope` from `scope_executor`; `print_scope_dry_run`, `print_scope_results`, `write_scope_log` from `reporter`

- [ ] **Step 1: Wire scope pipeline into run.py**

Replace `_cmd_scope` stub and add imports in `run.py`. The full updated file:

```python
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


def _cmd_merge(args):
    config = _load_config()
    entries = config.get("merges", [])
    if not entries:
        print("No merges defined in config.yaml.", file=sys.stderr)
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

    access_token, expires_in = get_token()
    token = {"t": access_token, "expiration": int(time.time()) + expires_in}
    session = make_session()

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
```

- [ ] **Step 2: Run full test suite**

```bash
pytest -v
```

Expected: all tests pass.

- [ ] **Step 3: Update README.md**

Replace the full content of `README.md`:

```markdown
# jamf_group_cleanup

Two subcommands for managing Jamf Pro group references:

- **`merge`** — adds all members from a source group into a target static group, then deletes the source
- **`scope`** — replaces a source group with a target group in all policy and config profile scopes (does not delete the source group)

## Setup

Requires `jamf_client` from `../jamf_client`.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file with your Jamf credentials:

```
JAMF_URL=https://yourschool.jamfcloud.com
CLIENT_ID=your-api-client-id
CLIENT_SECRET=your-api-client-secret
```

Credentials are stored encrypted at `../jamf_client/.env.age`. Decrypt to get your `.env`:

```sh
age --decrypt -o .env ../jamf_client/.env.age
```

`age` can be installed via Homebrew if needed:

```sh
brew install age
```

## Config

Copy `config.yaml.example` to `config.yaml` and define your operations:

```yaml
merges:
  # Merge by name (static → static)
  - source: "Old Staff Macs"
    target: "All Staff Computers"
    type: computer

  # Merge by Jamf ID (useful for names with special characters)
  - source: 4821
    target: "All Student iPads"
    type: mobile_device

  # Smart group as source — members are snapshotted at run time
  - source: "Retired iPad Smart Group"
    target: "All Student iPads"
    type: mobile_device

scopes:
  # Replace source group with target in all policy/profile scopes (computers)
  - source: "Old Staff Macs"
    target: "All Staff Computers"
    type: computer

  # Replace source group in mobile device profile scopes
  - source: "Old iPad Group"
    target: "All Student iPads"
    type: mobile_device
```

**Fields (both `merges` and `scopes` entries):**

| Field | Required | Description |
|---|---|---|
| `source` | yes | Group name (string) or Jamf ID (integer) |
| `target` | yes | Group name (string) or Jamf ID (integer) |
| `type` | yes | `computer` or `mobile_device` |

`merge` and `scope` subcommands are independent — each reads only its own config section.

## Usage

```sh
# Merge subcommand
./run.sh merge          # execute merges
./run.sh merge --dry    # preview merges, no changes

# Scope subcommand
./run.sh scope          # replace group references in scopes
./run.sh scope --dry    # preview scope changes, no changes
```

Both subcommands exit with a non-zero code if any entry fails.

Logs are written to `logs/<timestamp>.log`. The last 8 logs are kept automatically.

## Output

### merge

```
[OK]   Old Staff Macs → All Staff Computers  (42 added, 3 already present)
[SKIP] Retired iPad Pool → All Student iPads  (0 new members, source not deleted)
[FAIL] Old Lab Macs → All Lab Computers       (PUT 500: internal server error)

2 succeeded, 1 skipped, 1 failed
```

| Status | Meaning |
|---|---|
| `OK` | Members added to target, source deleted |
| `SKIP` | Source had no new members; source not deleted |
| `FAIL` | PUT or DELETE failed after retry; source not deleted |

### scope

```
[OK]   Old Group → New Group  (4 objects updated)
[SKIP] Old iPad Group → All iPads  (source group not found in any scope)
[FAIL] Old Lab Group → New Lab Group  (PUT 'Deploy Xcode' 500: error — source not deleted)

2 succeeded, 1 skipped, 0 failed
```

| Status | Meaning |
|---|---|
| `OK` | Source group replaced with target in all matching policy/profile scopes |
| `SKIP` | Source group not found in any scope; no changes made |
| `FAIL` | One or more PUT requests failed after retry; partially updated entries are not rolled back |

> **Note:** The `scope` subcommand never deletes the source group. It only replaces references in policy/profile scopes.

## Tests

```sh
pytest
```
```

- [ ] **Step 4: Run full test suite one final time**

```bash
pytest -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add run.py README.md
git commit -m "feat: wire scope pipeline into run.py, update README"
```

- [ ] **Step 6: Push**

```bash
git push
```
