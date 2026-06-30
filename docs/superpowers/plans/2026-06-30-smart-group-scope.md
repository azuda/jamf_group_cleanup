# Smart Group Scope Transfer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the `scope` command to also update smart group membership criteria that reference the source group, replacing them with the target group name — for both computer and mobile device group types.

**Architecture:** New `SmartGroupCriterionRef` dataclass lives in `scope_resolver.py` alongside `ScopedObject`. A new `_scan_smart_groups` function scans all smart groups for matching criteria and populates `ResolvedScope.smart_groups`. `execute_scope` gains a second loop that updates criteria XML via `_replace_criterion_value` and follows the same GET→PUT→verify pattern as the existing policy/profile loop. Reporter shows smart group counts alongside object counts.

**Tech Stack:** Python 3.14, xml.etree.ElementTree, requests, pytest, Jamf Classic API

## Global Constraints

- 2-space indentation throughout (match existing code style)
- No new dependencies
- All tests in `tests/` using pytest
- Run tests: `.venv/bin/python -m pytest tests/ -v`
- Run single test: `.venv/bin/python -m pytest tests/test_smart_group_scope.py -v`

---

### Task 1: Data model — `SmartGroupCriterionRef`, updated `ResolvedScope` and `ScopeResult`

**Files:**
- Modify: `scope_resolver.py`
- Modify: `scope_executor.py`

**Interfaces:**
- Produces: `SmartGroupCriterionRef(group_id, group_name, target_already_present=False)` — used by Tasks 2, 3, 4
- Produces: `ResolvedScope.smart_groups: list` — populated by Task 2, consumed by Tasks 3, 4
- Produces: `ScopeResult.smart_groups_updated: list` — populated by Task 3, consumed by Task 4

- [ ] **Step 1: Add `SmartGroupCriterionRef` to `scope_resolver.py`**

Add after the `ScopedObject` dataclass (around line 18):

```python
@dataclass
class SmartGroupCriterionRef:
  group_id: int
  group_name: str
  target_already_present: bool = False
```

- [ ] **Step 2: Add `smart_groups` field to `ResolvedScope` in `scope_resolver.py`**

The current `ResolvedScope` ends with `objects`. Add one field after it:

```python
@dataclass
class ResolvedScope:
  source_id: int
  source_name: str
  target_id: int
  target_name: str
  group_type: str
  objects: list = field(default_factory=list)
  smart_groups: list = field(default_factory=list)
```

- [ ] **Step 3: Add `smart_groups_updated` field to `ScopeResult` in `scope_executor.py`**

```python
@dataclass
class ScopeResult:
  resolved: ResolvedScope
  status: str
  objects_updated: list = field(default_factory=list)
  smart_groups_updated: list = field(default_factory=list)
  error: str | None = None
  skip_reason: str | None = None
```

- [ ] **Step 4: Verify existing tests still pass**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: all 69 tests pass. The new fields default to `[]` so no existing fixture breaks.

- [ ] **Step 5: Commit**

```bash
git add scope_resolver.py scope_executor.py
git commit -m "feat: add SmartGroupCriterionRef dataclass and smart_groups fields"
```

---

### Task 2: Scanner — `_scan_smart_groups` and updated `resolve_scope`

**Files:**
- Modify: `scope_resolver.py`
- Create: `tests/test_smart_group_scope.py`

**Interfaces:**
- Consumes: `SmartGroupCriterionRef` from Task 1
- Produces: `_scan_smart_groups(source_name, target_name, group_type, token, session) -> list[SmartGroupCriterionRef]`
- Produces: `SMART_CRITERION_NAME: dict` — consumed by Task 3

- [ ] **Step 1: Write the failing tests**

Create `tests/test_smart_group_scope.py`:

```python
from unittest.mock import MagicMock, patch
import xml.etree.ElementTree as ET
from scope_resolver import _scan_smart_groups, SmartGroupCriterionRef


# ── XML fixtures ─────────────────────────────────────────────────────────────

GROUP_LIST_XML = """<?xml version="1.0" encoding="UTF-8"?>
<computer_groups>
    <computer_group><id>10</id><name>Smart Group A</name><is_smart>true</is_smart></computer_group>
    <computer_group><id>11</id><name>Static Group B</name><is_smart>false</is_smart></computer_group>
</computer_groups>"""

SMART_SOURCE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<computer_group>
    <id>10</id><name>Smart Group A</name><is_smart>true</is_smart>
    <criteria>
        <criterion>
            <name>Computer Group</name>
            <search_type>member of</search_type>
            <value>Old Staff Macs</value>
        </criterion>
    </criteria>
    <computers/>
</computer_group>"""

SMART_BOTH_XML = """<?xml version="1.0" encoding="UTF-8"?>
<computer_group>
    <id>10</id><name>Smart Group A</name><is_smart>true</is_smart>
    <criteria>
        <criterion><name>Computer Group</name><value>Old Staff Macs</value></criterion>
        <criterion><name>Computer Group</name><value>All Staff Computers</value></criterion>
    </criteria>
    <computers/>
</computer_group>"""

SMART_NO_MATCH_XML = """<?xml version="1.0" encoding="UTF-8"?>
<computer_group>
    <id>10</id><name>Smart Group A</name><is_smart>true</is_smart>
    <criteria>
        <criterion>
            <name>Application Title</name>
            <search_type>is</search_type>
            <value>Safari.app</value>
        </criterion>
    </criteria>
    <computers/>
</computer_group>"""


# ── helpers ──────────────────────────────────────────────────────────────────

def _mock_response(status_code, text=""):
    r = MagicMock()
    r.status_code = status_code
    r.ok = status_code < 400
    r.text = text
    return r

def _make_token():
    return {"t": "tok", "expiration": 9999999999}


# ── _scan_smart_groups ───────────────────────────────────────────────────────

def test_scan_finds_matching_smart_group():
    responses = [_mock_response(200, GROUP_LIST_XML), _mock_response(200, SMART_SOURCE_XML)]
    with patch("scope_resolver.classic_get", side_effect=responses):
        result = _scan_smart_groups("Old Staff Macs", "All Staff Computers", "computer", _make_token(), MagicMock())
    assert len(result) == 1
    assert result[0].group_id == 10
    assert result[0].group_name == "Smart Group A"
    assert result[0].target_already_present is False


def test_scan_ignores_static_groups():
    # ID=11 is static; ID=10 has no matching criterion
    responses = [_mock_response(200, GROUP_LIST_XML), _mock_response(200, SMART_NO_MATCH_XML)]
    with patch("scope_resolver.classic_get", side_effect=responses):
        result = _scan_smart_groups("Old Staff Macs", "All Staff Computers", "computer", _make_token(), MagicMock())
    assert result == []


def test_scan_ignores_non_matching_criterion():
    responses = [_mock_response(200, GROUP_LIST_XML), _mock_response(200, SMART_NO_MATCH_XML)]
    with patch("scope_resolver.classic_get", side_effect=responses):
        result = _scan_smart_groups("Old Staff Macs", "All Staff Computers", "computer", _make_token(), MagicMock())
    assert result == []


def test_scan_sets_target_already_present():
    responses = [_mock_response(200, GROUP_LIST_XML), _mock_response(200, SMART_BOTH_XML)]
    with patch("scope_resolver.classic_get", side_effect=responses):
        result = _scan_smart_groups("Old Staff Macs", "All Staff Computers", "computer", _make_token(), MagicMock())
    assert len(result) == 1
    assert result[0].target_already_present is True


def test_scan_returns_empty_on_list_failure(capsys):
    with patch("scope_resolver.classic_get", return_value=_mock_response(403, "Forbidden")):
        result = _scan_smart_groups("Old Staff Macs", "All Staff Computers", "computer", _make_token(), MagicMock())
    assert result == []
    assert "WARNING" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/python -m pytest tests/test_smart_group_scope.py -v
```

Expected: `ImportError` or `AttributeError` — `_scan_smart_groups` not yet defined.

- [ ] **Step 3: Add constants and `_scan_smart_groups` to `scope_resolver.py`**

Add after the `OBJECT_TYPE_SPECS` dict:

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

Add the function after `_scan_object_type`:

```python
def _scan_smart_groups(source_name, target_name, group_type, token, session):
  list_response = classic_get(SMART_GROUP_LIST_PATH[group_type], token, session)
  if not list_response.ok:
    print(
      f"WARNING: could not list smart {group_type} groups "
      f"({list_response.status_code}) — skipped",
      file=sys.stderr,
    )
    return []

  root = ET.fromstring(list_response.text)
  tag = "computer_group" if group_type == "computer" else "mobile_device_group"
  detail_base = SMART_GROUP_LIST_PATH[group_type] + "/id/{}"
  criterion_name = SMART_CRITERION_NAME[group_type]

  results = []
  for el in root.findall(tag):
    is_smart_text = el.findtext("is_smart")
    if is_smart_text == "false":
      continue
    gid = int(el.findtext("id"))

    detail_response = classic_get(detail_base.format(gid), token, session)
    if not detail_response.ok:
      print(
        f"WARNING: could not fetch smart group id={gid} "
        f"({detail_response.status_code}) — skipped",
        file=sys.stderr,
      )
      continue

    detail_root = ET.fromstring(detail_response.text)

    # fall back to detail for is_smart when absent from list
    if is_smart_text is None and detail_root.findtext("is_smart") == "false":
      continue

    group_name = detail_root.findtext("name") or ""
    source_found = False
    target_found = False

    for criterion in detail_root.findall("criteria/criterion"):
      cname = criterion.findtext("name")
      cvalue = criterion.findtext("value")
      if cname == criterion_name:
        if cvalue == source_name:
          source_found = True
        elif cvalue == target_name:
          target_found = True

    if source_found:
      results.append(SmartGroupCriterionRef(
        group_id=gid,
        group_name=group_name,
        target_already_present=target_found,
      ))

  return results
```

- [ ] **Step 4: Update `resolve_scope` to call `_scan_smart_groups`**

In `resolve_scope`, replace the final `resolved.append(...)` block:

```python
    all_objects = []
    for spec in OBJECT_TYPE_SPECS[group_type]:
      all_objects.extend(_scan_object_type(spec, source["id"], target["id"], token, session))

    smart_groups = _scan_smart_groups(source["name"], target["name"], group_type, token, session)

    resolved.append(ResolvedScope(
      source_id=source["id"],
      source_name=source["name"],
      target_id=target["id"],
      target_name=target["name"],
      group_type=group_type,
      objects=all_objects,
      smart_groups=smart_groups,
    ))
```

- [ ] **Step 5: Run scanner tests**

```bash
.venv/bin/python -m pytest tests/test_smart_group_scope.py -v
```

Expected: all 5 scanner tests PASS.

- [ ] **Step 6: Run full suite to check for regressions**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: all 69 + 5 = 74 tests pass.

- [ ] **Step 7: Commit**

```bash
git add scope_resolver.py tests/test_smart_group_scope.py
git commit -m "feat: scan smart groups for source group criteria"
```

---

### Task 3: Executor — `_replace_criterion_value`, `_source_criterion_present`, updated `execute_scope`

**Files:**
- Modify: `scope_executor.py`
- Modify: `tests/test_smart_group_scope.py`

**Interfaces:**
- Consumes: `SmartGroupCriterionRef` from Task 1, `SMART_CRITERION_NAME` from Task 2
- Produces: `_replace_criterion_value(xml_text, criterion_name, source_name, target_name) -> str`
- Produces: `_source_criterion_present(xml_text, criterion_name, source_name) -> bool`

- [ ] **Step 1: Write the failing executor tests**

First, add these imports to the **top** of `tests/test_smart_group_scope.py` (alongside the existing ones):

```python
import scope_executor
from scope_executor import _replace_criterion_value, _source_criterion_present, ScopeResult
from scope_resolver import ResolvedScope, SmartGroupCriterionRef
```

(`_mock_response` and `_make_token` are already defined in the file from Task 2 — do not redefine them.)

Then append the following tests to the bottom of `tests/test_smart_group_scope.py`:

```python


# ── XML fixtures (executor) ──────────────────────────────────────────────────

CRITERION_XML = """<computer_group>
    <id>10</id><name>Smart Group A</name><is_smart>true</is_smart>
    <criteria>
        <criterion><name>Computer Group</name><value>Old Staff Macs</value></criterion>
        <criterion><name>Application Title</name><value>Safari.app</value></criterion>
    </criteria>
</computer_group>"""

CRITERION_DOUBLE_XML = """<computer_group>
    <id>10</id><name>Smart Group A</name><is_smart>true</is_smart>
    <criteria>
        <criterion><name>Computer Group</name><and_or>and</and_or><value>Old Staff Macs</value></criterion>
        <criterion><name>Computer Group</name><and_or>or</and_or><value>Old Staff Macs</value></criterion>
    </criteria>
</computer_group>"""

EXEC_SMART_SOURCE_XML = """<computer_group>
    <id>10</id><name>Smart Group A</name><is_smart>true</is_smart>
    <criteria><criterion><name>Computer Group</name><value>Old Staff Macs</value></criterion></criteria>
</computer_group>"""

EXEC_SMART_TARGET_XML = """<computer_group>
    <id>10</id><name>Smart Group A</name><is_smart>true</is_smart>
    <criteria><criterion><name>Computer Group</name><value>All Staff Computers</value></criterion></criteria>
</computer_group>"""


# ── helpers (executor) ───────────────────────────────────────────────────────

def _make_rs_smart(smart_groups):
    return ResolvedScope(
        source_id=1, source_name="Old Staff Macs",
        target_id=2, target_name="All Staff Computers",
        group_type="computer",
        objects=[],
        smart_groups=smart_groups,
    )

def _make_sg(already=False):
    return SmartGroupCriterionRef(group_id=10, group_name="Smart Group A", target_already_present=already)


# ── _replace_criterion_value ─────────────────────────────────────────────────

def test_replace_criterion_updates_matching():
    result = _replace_criterion_value(CRITERION_XML, "Computer Group", "Old Staff Macs", "All Staff Computers")
    root = ET.fromstring(result)
    crit = next(c for c in root.findall("criteria/criterion") if c.findtext("name") == "Computer Group")
    assert crit.findtext("value") == "All Staff Computers"


def test_replace_criterion_leaves_other_criteria_untouched():
    result = _replace_criterion_value(CRITERION_XML, "Computer Group", "Old Staff Macs", "All Staff Computers")
    root = ET.fromstring(result)
    app_crit = next(c for c in root.findall("criteria/criterion") if c.findtext("name") == "Application Title")
    assert app_crit.findtext("value") == "Safari.app"


def test_replace_criterion_replaces_all_matches():
    result = _replace_criterion_value(CRITERION_DOUBLE_XML, "Computer Group", "Old Staff Macs", "All Staff Computers")
    root = ET.fromstring(result)
    for c in root.findall("criteria/criterion"):
        assert c.findtext("value") == "All Staff Computers"


# ── _source_criterion_present ────────────────────────────────────────────────

def test_source_criterion_present_returns_true_when_found():
    assert _source_criterion_present(EXEC_SMART_SOURCE_XML, "Computer Group", "Old Staff Macs") is True


def test_source_criterion_present_returns_false_when_not_found():
    assert _source_criterion_present(EXEC_SMART_TARGET_XML, "Computer Group", "Old Staff Macs") is False


# ── execute_scope — smart groups ─────────────────────────────────────────────

def test_execute_scope_smart_group_ok():
    rs = _make_rs_smart([_make_sg()])
    with patch("scope_executor.classic_get", return_value=_mock_response(200, EXEC_SMART_SOURCE_XML)), \
         patch("scope_executor.put_with_retry", return_value=_mock_response(200)):
        results = scope_executor.execute_scope([rs], _make_token(), MagicMock())
    assert results[0].status == "OK"
    assert len(results[0].smart_groups_updated) == 1
    assert results[0].smart_groups_updated[0].group_id == 10


def test_execute_scope_smart_group_skip_when_already_present():
    rs = _make_rs_smart([_make_sg(already=True)])
    with patch("scope_executor.put_with_retry") as mock_put:
        results = scope_executor.execute_scope([rs], _make_token(), MagicMock())
    mock_put.assert_not_called()
    assert results[0].status == "SKIP"
    assert results[0].skip_reason == "all_noop"


def test_execute_scope_smart_group_put_fail_verify_applied(capsys):
    rs = _make_rs_smart([_make_sg()])
    get_responses = [_mock_response(200, EXEC_SMART_SOURCE_XML), _mock_response(200, EXEC_SMART_TARGET_XML)]
    with patch("scope_executor.classic_get", side_effect=get_responses), \
         patch("scope_executor.put_with_retry", return_value=_mock_response(409, "Problem with script")):
        results = scope_executor.execute_scope([rs], _make_token(), MagicMock())
    assert results[0].status == "OK"
    assert len(results[0].smart_groups_updated) == 1
    assert "WARNING" in capsys.readouterr().err


def test_execute_scope_smart_group_put_fail_verify_still_present():
    rs = _make_rs_smart([_make_sg()])
    get_responses = [_mock_response(200, EXEC_SMART_SOURCE_XML), _mock_response(200, EXEC_SMART_SOURCE_XML)]
    with patch("scope_executor.classic_get", side_effect=get_responses), \
         patch("scope_executor.put_with_retry", return_value=_mock_response(500, "server error")):
        results = scope_executor.execute_scope([rs], _make_token(), MagicMock())
    assert results[0].status == "FAIL"
    assert "500" in results[0].error


def test_execute_scope_smart_group_continues_after_fail():
    sg1 = SmartGroupCriterionRef(group_id=10, group_name="Smart Group A")
    sg2 = SmartGroupCriterionRef(group_id=11, group_name="Smart Group B")
    rs = _make_rs_smart([sg1, sg2])

    # sg1: initial GET, verify GET (source still present → true FAIL); sg2: initial GET
    get_responses = [
        _mock_response(200, EXEC_SMART_SOURCE_XML),  # sg1 initial GET
        _mock_response(200, EXEC_SMART_SOURCE_XML),  # sg1 verify GET — still present
        _mock_response(200, EXEC_SMART_SOURCE_XML),  # sg2 initial GET
    ]
    put_responses = [_mock_response(500, "err"), _mock_response(200)]

    with patch("scope_executor.classic_get", side_effect=get_responses), \
         patch("scope_executor.put_with_retry", side_effect=put_responses):
        results = scope_executor.execute_scope([rs], _make_token(), MagicMock())

    assert results[0].status == "FAIL"
    assert len(results[0].smart_groups_updated) == 1
    assert results[0].smart_groups_updated[0].group_id == 11
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/python -m pytest tests/test_smart_group_scope.py -v
```

Expected: `ImportError` for `_replace_criterion_value`, `_source_criterion_present`.

- [ ] **Step 3: Add helpers and constants to `scope_executor.py`**

Replace the existing `from scope_resolver import ...` line at the top of `scope_executor.py` with:

```python
from scope_resolver import ResolvedScope, ScopedObject, SmartGroupCriterionRef, _check_object_for_group, SMART_CRITERION_NAME
```

Add after `EXCLUDE_PATH_BY_GROUP_TYPE`:

```python
SMART_GROUP_PUT_PATH = {
  "computer": "/JSSResource/computergroups/id/{}",
  "mobile_device": "/JSSResource/mobiledevicegroups/id/{}",
}
```

Add after `_replace_group_in_xml`:

```python
def _replace_criterion_value(xml_text, criterion_name, source_name, target_name):
  root = ET.fromstring(xml_text)
  for el in root.findall("criteria/criterion"):
    if el.findtext("name") == criterion_name and el.findtext("value") == source_name:
      el.find("value").text = target_name
  return ET.tostring(root, encoding="unicode")


def _source_criterion_present(xml_text, criterion_name, source_name):
  root = ET.fromstring(xml_text)
  return any(
    el.findtext("name") == criterion_name and el.findtext("value") == source_name
    for el in root.findall("criteria/criterion")
  )
```

- [ ] **Step 4: Replace `execute_scope` with the updated version**

Replace the entire `execute_scope` function with:

```python
def execute_scope(resolved_scopes, token, session):
  results = []
  for rs in resolved_scopes:
    actionable = [obj for obj in rs.objects if not obj.target_already_present]
    actionable_sg = [sg for sg in rs.smart_groups if not sg.target_already_present]

    if not actionable and not actionable_sg:
      reason = "all_noop" if (rs.objects or rs.smart_groups) else "not_found"
      results.append(ScopeResult(resolved=rs, status="SKIP", skip_reason=reason))
      continue

    include_path = INCLUDE_PATH_BY_GROUP_TYPE[rs.group_type]
    exclude_path = EXCLUDE_PATH_BY_GROUP_TYPE[rs.group_type]
    criterion_name = SMART_CRITERION_NAME[rs.group_type]
    objects_updated = []
    smart_groups_updated = []
    failed = False
    fail_errors = []

    for obj in actionable:
      put_path = DETAIL_PATH_BY_TYPE[obj.object_type].format(obj.object_id)

      get_response = classic_get(put_path, token, session)
      if not get_response.ok:
        failed = True
        fail_errors.append(f"GET '{obj.object_name}' {get_response.status_code}: {get_response.text[:200]}")
        continue

      fresh_inc, fresh_exc, fresh_target_present = _check_object_for_group(
        get_response.text, rs.source_id, rs.target_id, include_path, exclude_path
      )
      if fresh_target_present:
        continue

      updated_xml = _replace_group_in_xml(
        get_response.text, rs.source_id, rs.target_id, rs.target_name,
        include_path, exclude_path, fresh_inc, fresh_exc,
      )

      put_response = put_with_retry(put_path, updated_xml, token, session)

      if not put_response.ok:
        verify_response = classic_get(put_path, token, session)
        if verify_response.ok:
          v_inc, v_exc, _ = _check_object_for_group(
            verify_response.text, rs.source_id, rs.target_id, include_path, exclude_path
          )
          if not v_inc and not v_exc:
            print(
              f"  WARNING: PUT '{obj.object_name}' returned {put_response.status_code} "
              f"but scope change applied — Jamf reported: {put_response.text[:120]}",
              file=sys.stderr,
            )
            objects_updated.append(obj)
            continue
        failed = True
        fail_errors.append(f"PUT '{obj.object_name}' {put_response.status_code}: {put_response.text[:200]}")
      else:
        objects_updated.append(obj)

    for sg in actionable_sg:
      put_path = SMART_GROUP_PUT_PATH[rs.group_type].format(sg.group_id)

      get_response = classic_get(put_path, token, session)
      if not get_response.ok:
        failed = True
        fail_errors.append(f"GET smart group '{sg.group_name}' {get_response.status_code}: {get_response.text[:200]}")
        continue

      if not _source_criterion_present(get_response.text, criterion_name, rs.source_name):
        continue  # another admin already updated it

      updated_xml = _replace_criterion_value(get_response.text, criterion_name, rs.source_name, rs.target_name)

      put_response = put_with_retry(put_path, updated_xml, token, session)

      if not put_response.ok:
        verify_response = classic_get(put_path, token, session)
        if verify_response.ok and not _source_criterion_present(verify_response.text, criterion_name, rs.source_name):
          print(
            f"  WARNING: PUT smart group '{sg.group_name}' returned {put_response.status_code} "
            f"but criterion change applied — Jamf reported: {put_response.text[:120]}",
            file=sys.stderr,
          )
          smart_groups_updated.append(sg)
          continue
        failed = True
        fail_errors.append(f"PUT smart group '{sg.group_name}' {put_response.status_code}: {put_response.text[:200]}")
      else:
        smart_groups_updated.append(sg)

    if failed:
      results.append(ScopeResult(
        resolved=rs, status="FAIL",
        objects_updated=objects_updated,
        smart_groups_updated=smart_groups_updated,
        error="; ".join(fail_errors),
      ))
    else:
      results.append(ScopeResult(
        resolved=rs, status="OK",
        objects_updated=objects_updated,
        smart_groups_updated=smart_groups_updated,
      ))

  return results
```

- [ ] **Step 5: Run executor tests**

```bash
.venv/bin/python -m pytest tests/test_smart_group_scope.py -v
```

Expected: all tests in the file PASS.

- [ ] **Step 6: Run full suite**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add scope_executor.py tests/test_smart_group_scope.py
git commit -m "feat: update smart group criteria in execute_scope"
```

---

### Task 4: Reporter — dry run and results output for smart groups

**Files:**
- Modify: `reporter.py`
- Modify: `tests/test_reporter.py`

**Interfaces:**
- Consumes: `ResolvedScope.smart_groups`, `ScopeResult.smart_groups_updated` from Tasks 1–3

- [ ] **Step 1: Write the failing reporter tests**

Open `tests/test_reporter.py`. Ensure `print_scope_dry_run` and `print_scope_results` are in the existing imports at the top (they should be — the file imports from `reporter`). Then append:

```python
from scope_resolver import ResolvedScope, ScopedObject, SmartGroupCriterionRef
from scope_executor import ScopeResult


def _make_rs_with_smart(smart_groups, objects=None):
    return ResolvedScope(
        source_id=1, source_name="Old Group",
        target_id=2, target_name="New Group",
        group_type="computer",
        objects=objects or [],
        smart_groups=smart_groups,
    )


def test_print_scope_dry_run_shows_smart_group_count(capsys):
    sg = SmartGroupCriterionRef(group_id=10, group_name="Smart Group A")
    rs = _make_rs_with_smart([sg])
    print_scope_dry_run([rs])
    out = capsys.readouterr().out
    assert "smart groups" in out
    assert "1" in out


def test_print_scope_dry_run_shows_noop_smart_group(capsys):
    sg = SmartGroupCriterionRef(group_id=10, group_name="Smart Group A", target_already_present=True)
    rs = _make_rs_with_smart([sg])
    print_scope_dry_run([rs])
    out = capsys.readouterr().out
    assert "smart groups" in out
    assert "no-op" in out


def test_print_scope_dry_run_omits_smart_groups_section_when_empty(capsys):
    rs = _make_rs_with_smart([])
    print_scope_dry_run([rs])
    out = capsys.readouterr().out
    assert "smart groups" not in out


def test_print_scope_results_shows_smart_groups_updated(capsys):
    rs = _make_rs_with_smart([])
    sg = SmartGroupCriterionRef(group_id=10, group_name="Smart Group A")
    result = ScopeResult(resolved=rs, status="OK", smart_groups_updated=[sg])
    print_scope_results([result])
    out = capsys.readouterr().out
    assert "1 smart group" in out


def test_print_scope_results_omits_smart_groups_when_none_updated(capsys):
    rs = _make_rs_with_smart([])
    result = ScopeResult(resolved=rs, status="OK")
    print_scope_results([result])
    out = capsys.readouterr().out
    assert "smart group" not in out
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/python -m pytest tests/test_reporter.py -v -k "smart"
```

Expected: FAIL — reporter functions don't yet reference `smart_groups`.

- [ ] **Step 3: Update `print_scope_dry_run` in `reporter.py`**

Replace `print_scope_dry_run` with:

```python
def print_scope_dry_run(resolved_scopes):
  print("DRY RUN — no changes will be made\n")
  for i, rs in enumerate(resolved_scopes, 1):
    print(f"[{i}] {rs.source_name} ({rs.group_type}) → {rs.target_name}")
    noop = [o for o in rs.objects if o.target_already_present]

    if rs.group_type == "computer":
      policies = [o for o in rs.objects if o.object_type == "policy" and not o.target_already_present]
      osx = [o for o in rs.objects if o.object_type == "osx_profile" and not o.target_already_present]
      print(f"    computer policies:     {len(policies)} would be updated")
      print(f"    macOS config profiles: {len(osx)} would be updated")
    else:
      mobile = [o for o in rs.objects if o.object_type == "mobile_profile" and not o.target_already_present]
      apps = [o for o in rs.objects if o.object_type == "mobile_app" and not o.target_already_present]
      print(f"    mobile device profiles: {len(mobile)} would be updated")
      print(f"    mobile device apps:     {len(apps)} would be updated")

    if noop:
      print(f"    Already has target:    {len(noop)} object(s) (no-op)")

    if rs.smart_groups:
      sg_actionable = [sg for sg in rs.smart_groups if not sg.target_already_present]
      sg_noop = [sg for sg in rs.smart_groups if sg.target_already_present]
      line = f"    smart groups:          {len(sg_actionable)} would be updated"
      if sg_noop:
        line += f", {len(sg_noop)} already reference target (no-op)"
      print(line)

    if not rs.objects and not rs.smart_groups:
      print("    (source group not found in any scope — would be skipped)")
    print()
```

- [ ] **Step 4: Update `print_scope_results` in `reporter.py`**

Replace `print_scope_results` with:

```python
def print_scope_results(results):
  for r in results:
    rs = r.resolved
    n = len(r.objects_updated)
    sg_n = len(r.smart_groups_updated)
    if r.status == "OK":
      parts = []
      if n:
        parts.append(f"{n} object{'s' if n != 1 else ''} updated")
      if sg_n:
        parts.append(f"{sg_n} smart group{'s' if sg_n != 1 else ''} updated")
      summary = ", ".join(parts) if parts else "0 objects updated"
      print(f"[OK]   {rs.source_name} → {rs.target_name}  ({summary})")
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
```

- [ ] **Step 5: Update `write_scope_log` in `reporter.py`**

Replace `write_scope_log` with:

```python
def write_scope_log(results, log_path):
  with _open_log(log_path) as f:
    for r in results:
      rs = r.resolved
      f.write(f"scope: status={r.status} source={rs.source_name}(id={rs.source_id}) target={rs.target_name}(id={rs.target_id}) type={rs.group_type}\n")
      for obj in r.objects_updated:
        f.write(f"  updated: {obj.object_type} '{obj.object_name}' (id={obj.object_id})\n")
      for sg in r.smart_groups_updated:
        f.write(f"  updated: smart_group '{sg.group_name}' (id={sg.group_id})\n")
      if r.objects_updated or r.smart_groups_updated:
        f.write(f"  NOTE: '{rs.source_name}' (id={rs.source_id}) scope references replaced by '{rs.target_name}' (id={rs.target_id}) — group not deleted\n")
      if r.error:
        f.write(f"  error={r.error}\n")
```

- [ ] **Step 6: Run reporter tests**

```bash
.venv/bin/python -m pytest tests/test_reporter.py -v
```

Expected: all reporter tests PASS.

- [ ] **Step 7: Run full suite**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add reporter.py tests/test_reporter.py
git commit -m "feat: show smart group counts in scope dry run and results"
```
