# Jamf Group Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A config-driven Python script that merges Jamf Pro groups by adding source members to a target static group and deleting the source.

**Architecture:** Three-phase pipeline — resolve (validate + snapshot), dry-run output or execute (PUT members + DELETE source), report. Each phase is a separate module. `run.py` orchestrates them with token lifecycle and argparse.

**Tech Stack:** Python 3.11+, `jamf_client` (local package `../jamf_client`), `pyyaml`, `pytest`, Jamf Classic API (XML over HTTPS).

## Global Constraints

- Python 3.11+ (matches `jamf_client` requirement)
- `jamf_client` from `../jamf_client` (editable install via `-e ../jamf_client`)
- All classic API calls use bearer token auth via `jamf_client.get_token()` / `check_token_expiration()`
- Classic API base URL from `jamf_client.JAMF_URL` (loaded from `.env`)
- Config file is always `merge.yaml` (relative to CWD, gitignored)
- Log files go to `logs/`, debug dumps to `debug/`, keep last 8 logs
- `--dry` flag: validate + print plan, no writes
- Source group deleted only if all members were added successfully (PUT succeeded)
- Smart targets are rejected at validation time; smart sources are snapshotted
- On PUT failure: retry once, then mark FAIL and continue
- Group names are URL-encoded when used in classic API paths

---

## File Map

| File | Responsibility |
|---|---|
| `requirements.txt` | Declares dependencies |
| `run.sh` | Venv activation, log path env var, log rotation, passes `"$@"` to `run.py` |
| `run.py` | Entry point: argparse, yaml load, token lifecycle, phase orchestration |
| `merge.yaml.example` | Annotated example config (committed; `merge.yaml` itself is gitignored) |
| `api.py` | Classic API helpers: `classic_get`, `classic_put`, `classic_delete` |
| `resolver.py` | Data classes; group lookup; XML parsing; `resolve()` |
| `executor.py` | Member XML building; PUT with retry; DELETE; `execute()` |
| `reporter.py` | Dry-run output; result summary; log writing |
| `tests/__init__.py` | Empty (makes tests a package) |
| `tests/test_api.py` | Unit tests for api.py |
| `tests/test_resolver.py` | Unit tests for resolver.py |
| `tests/test_executor.py` | Unit tests for executor.py |
| `tests/test_reporter.py` | Unit tests for reporter.py |
| `.gitignore` | Excludes `.env`, `merge.yaml`, `logs/`, `debug/`, `__pycache__/`, `.venv/` |

---

## Task 1: Project Scaffold

**Files:**
- Create: `requirements.txt`
- Create: `run.sh`
- Create: `.gitignore`
- Create: `merge.yaml.example`
- Create: `tests/__init__.py`
- Create: `logs/.gitkeep`
- Create: `debug/.gitkeep`

No test cycle for scaffold — verify by running `pip install -r requirements.txt` and `pytest` (zero tests pass).

- [ ] **Step 1: Create `requirements.txt`**

```
-e ../jamf_client
pyyaml
pytest
```

- [ ] **Step 2: Create `run.sh`**

```sh
#!/bin/sh

PROJECT="$PWD"
VENV="$PROJECT/.venv/bin/python3"

LOG_DIR="$PROJECT/logs"
timestamp=$(date '+%Y%m%d %H%M')
export LOG_FILE="$LOG_DIR/$timestamp.log"

mkdir -p "$LOG_DIR"
ls -1t "$LOG_DIR" | tail -n +9 | xargs -I {} rm -f "$LOG_DIR/{}"

echo "Script start @ $(date)"
$VENV -u run.py "$@"
echo "Script done @ $(date)"
```

```bash
chmod +x run.sh
```

- [ ] **Step 3: Create `.gitignore`**

```
.env
merge.yaml
logs/
debug/
__pycache__/
.venv/
*.pyc
```

- [ ] **Step 4: Create `merge.yaml.example`**

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
```

- [ ] **Step 5: Create `tests/__init__.py`** (empty file)

- [ ] **Step 6: Create `logs/.gitkeep` and `debug/.gitkeep`** (empty files)

- [ ] **Step 7: Set up venv and verify pytest runs**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
```

Expected: `no tests ran` or `0 passed`.

- [ ] **Step 8: Commit**

```bash
git init
git add requirements.txt run.sh .gitignore merge.yaml.example tests/__init__.py logs/.gitkeep debug/.gitkeep docs/
git commit -m "chore: project scaffold"
```

---

## Task 2: `api.py` — Classic API Helpers

**Files:**
- Create: `api.py`
- Create: `tests/test_api.py`

**Interfaces:**
- Produces:
  - `classic_get(path: str, token: dict, session: requests.Session) -> requests.Response`
  - `classic_put(path: str, xml_body: str, token: dict, session: requests.Session) -> requests.Response`
  - `classic_delete(path: str, token: dict, session: requests.Session) -> requests.Response`
  - `token` dict shape: `{"t": str, "expiration": int}` — same shape as used in `jamf_client.jamf_get`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_api.py
from unittest.mock import MagicMock, patch
import api


def _make_token():
    return {"t": "test-token", "expiration": 9999999999}


def test_classic_get_sets_bearer_header():
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=200)
    token = _make_token()

    with patch("api.JAMF_URL", "https://jamf.example.com"):
        with patch("api.check_token_expiration", return_value=("test-token", 9999999999)):
            api.classic_get("/JSSResource/computergroups/id/1", token, session)

    call_kwargs = session.get.call_args
    assert call_kwargs[0][0] == "https://jamf.example.com/JSSResource/computergroups/id/1"
    headers = call_kwargs[1]["headers"]
    assert headers["Authorization"] == "Bearer test-token"
    assert "application/xml" in headers["Accept"]


def test_classic_put_sends_xml_body():
    session = MagicMock()
    session.put.return_value = MagicMock(status_code=201)
    token = _make_token()
    xml = "<computer_group><computers></computers></computer_group>"

    with patch("api.JAMF_URL", "https://jamf.example.com"):
        with patch("api.check_token_expiration", return_value=("test-token", 9999999999)):
            api.classic_put("/JSSResource/computergroups/id/1", xml, token, session)

    call_kwargs = session.put.call_args
    assert call_kwargs[1]["data"] == xml
    headers = call_kwargs[1]["headers"]
    assert "application/xml" in headers["Content-Type"]


def test_classic_delete_sends_delete():
    session = MagicMock()
    session.delete.return_value = MagicMock(status_code=200)
    token = _make_token()

    with patch("api.JAMF_URL", "https://jamf.example.com"):
        with patch("api.check_token_expiration", return_value=("test-token", 9999999999)):
            api.classic_delete("/JSSResource/computergroups/id/1", token, session)

    assert session.delete.called
    call_kwargs = session.delete.call_args
    assert "Authorization" in call_kwargs[1]["headers"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_api.py -v
```

Expected: `ImportError` or `AttributeError` — `api` module doesn't exist yet.

- [ ] **Step 3: Implement `api.py`**

```python
from jamf_client import JAMF_URL, check_token_expiration


def classic_get(path, token, session):
    token["t"], token["expiration"] = check_token_expiration(token["t"], token["expiration"])
    return session.get(
        f"{JAMF_URL}{path}",
        headers={
            "Accept": "application/xml",
            "Authorization": f"Bearer {token['t']}",
        },
    )


def classic_put(path, xml_body, token, session):
    token["t"], token["expiration"] = check_token_expiration(token["t"], token["expiration"])
    return session.put(
        f"{JAMF_URL}{path}",
        headers={
            "Accept": "application/xml",
            "Content-Type": "application/xml",
            "Authorization": f"Bearer {token['t']}",
        },
        data=xml_body,
    )


def classic_delete(path, token, session):
    token["t"], token["expiration"] = check_token_expiration(token["t"], token["expiration"])
    return session.delete(
        f"{JAMF_URL}{path}",
        headers={
            "Authorization": f"Bearer {token['t']}",
        },
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_api.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add api.py tests/test_api.py
git commit -m "feat: classic API helpers (get/put/delete)"
```

---

## Task 3: `resolver.py` — Data Classes and XML Parsing

**Files:**
- Create: `resolver.py`
- Create: `tests/test_resolver.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass
  class MergeConfig:
      source: str | int
      target: str | int
      group_type: str  # "computer" or "mobile_device"

  @dataclass
  class ResolvedMerge:
      source_id: int
      source_name: str
      source_is_smart: bool
      source_members: list[int]
      target_id: int
      target_name: str
      target_members: list[int]
      group_type: str
      delta: list[int]         # source_members not already in target
      already_present: list[int]  # source_members already in target

  @dataclass
  class ValidationError:
      index: int   # 0-based entry index in the YAML merges list
      message: str

  def _parse_group_xml(xml_text: str, group_type: str) -> dict
  # Returns: {"id": int, "name": str, "is_smart": bool, "members": list[int]}
  ```

- [ ] **Step 1: Write failing tests for `_parse_group_xml`**

```python
# tests/test_resolver.py
import resolver
from resolver import MergeConfig, ResolvedMerge, ValidationError


COMPUTER_GROUP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<computer_group>
    <id>1</id>
    <name>Staff Macs</name>
    <is_smart>false</is_smart>
    <computers>
        <computer><id>101</id><name>Mac-01</name></computer>
        <computer><id>102</id><name>Mac-02</name></computer>
    </computers>
</computer_group>"""

SMART_COMPUTER_GROUP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<computer_group>
    <id>2</id>
    <name>Smart Group</name>
    <is_smart>true</is_smart>
    <computers>
        <computer><id>201</id><name>Mac-03</name></computer>
    </computers>
</computer_group>"""

MOBILE_GROUP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<mobile_device_group>
    <id>3</id>
    <name>All iPads</name>
    <is_smart>false</is_smart>
    <mobile_devices>
        <mobile_device><id>301</id><name>iPad-01</name></mobile_device>
    </mobile_devices>
</mobile_device_group>"""

EMPTY_GROUP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<computer_group>
    <id>4</id>
    <name>Empty Group</name>
    <is_smart>false</is_smart>
    <computers/>
</computer_group>"""


def test_parse_computer_group():
    result = resolver._parse_group_xml(COMPUTER_GROUP_XML, "computer")
    assert result["id"] == 1
    assert result["name"] == "Staff Macs"
    assert result["is_smart"] is False
    assert result["members"] == [101, 102]


def test_parse_smart_computer_group():
    result = resolver._parse_group_xml(SMART_COMPUTER_GROUP_XML, "computer")
    assert result["is_smart"] is True
    assert result["members"] == [201]


def test_parse_mobile_device_group():
    result = resolver._parse_group_xml(MOBILE_GROUP_XML, "mobile_device")
    assert result["id"] == 3
    assert result["name"] == "All iPads"
    assert result["members"] == [301]


def test_parse_empty_group():
    result = resolver._parse_group_xml(EMPTY_GROUP_XML, "computer")
    assert result["members"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_resolver.py -v
```

Expected: `ImportError` — `resolver` doesn't exist yet.

- [ ] **Step 3: Implement data classes and `_parse_group_xml` in `resolver.py`**

```python
from dataclasses import dataclass, field
import xml.etree.ElementTree as ET


@dataclass
class MergeConfig:
    source: str | int
    target: str | int
    group_type: str


@dataclass
class ResolvedMerge:
    source_id: int
    source_name: str
    source_is_smart: bool
    source_members: list
    target_id: int
    target_name: str
    target_members: list
    group_type: str
    delta: list = field(default_factory=list)
    already_present: list = field(default_factory=list)


@dataclass
class ValidationError:
    index: int
    message: str


def _parse_group_xml(xml_text, group_type):
    root = ET.fromstring(xml_text)
    group_id = int(root.findtext("id"))
    name = root.findtext("name")
    is_smart = root.findtext("is_smart") == "true"

    if group_type == "computer":
        member_path = "computers/computer"
    else:
        member_path = "mobile_devices/mobile_device"

    members = [int(c.findtext("id")) for c in root.findall(member_path)]
    return {"id": group_id, "name": name, "is_smart": is_smart, "members": members}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_resolver.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add resolver.py tests/test_resolver.py
git commit -m "feat: resolver data classes and XML parser"
```

---

## Task 4: `resolver.py` — `_lookup_group` and `resolve()`

**Files:**
- Modify: `resolver.py` (add `_lookup_group`, `resolve`)
- Modify: `tests/test_resolver.py` (add tests)

**Interfaces:**
- Consumes: `_parse_group_xml`, `MergeConfig`, `ResolvedMerge`, `ValidationError` from Task 3; `classic_get` from Task 2
- Produces:
  ```python
  def _lookup_group(ref: str | int, group_type: str, token: dict, session) -> dict | None
  # Returns parsed group dict or None if 404

  def resolve(entries: list[dict], token: dict, session) -> tuple[list[ResolvedMerge], list[ValidationError]]
  # entries: raw dicts from YAML, each with keys: source, target, type
  ```

- [ ] **Step 1: Write failing tests for `_lookup_group` and `resolve`**

Append to `tests/test_resolver.py`:

```python
from unittest.mock import MagicMock, patch


def _mock_response(status_code, text=""):
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    r.ok = status_code < 400
    r.raise_for_status = MagicMock()
    return r


def _make_token():
    return {"t": "tok", "expiration": 9999999999}


def test_lookup_group_by_name_found():
    session = MagicMock()
    token = _make_token()
    with patch("resolver.classic_get", return_value=_mock_response(200, COMPUTER_GROUP_XML)) as mock_get:
        result = resolver._lookup_group("Staff Macs", "computer", token, session)
    assert result["id"] == 1
    assert result["name"] == "Staff Macs"
    call_path = mock_get.call_args[0][0]
    assert "Staff%20Macs" in call_path or "Staff+Macs" in call_path or "Staff Macs" in call_path


def test_lookup_group_by_id_found():
    session = MagicMock()
    token = _make_token()
    with patch("resolver.classic_get", return_value=_mock_response(200, COMPUTER_GROUP_XML)):
        result = resolver._lookup_group(1, "computer", token, session)
    assert result["id"] == 1


def test_lookup_group_not_found_returns_none():
    session = MagicMock()
    token = _make_token()
    with patch("resolver.classic_get", return_value=_mock_response(404)):
        result = resolver._lookup_group("Nonexistent", "computer", token, session)
    assert result is None


def test_resolve_valid_entries():
    entries = [
        {"source": "Staff Macs", "target": "All Staff Computers", "type": "computer"}
    ]
    token = _make_token()
    session = MagicMock()

    source_xml = COMPUTER_GROUP_XML  # id=1, name="Staff Macs", members=[101,102]
    target_xml = """<?xml version="1.0" encoding="UTF-8"?>
<computer_group>
    <id>5</id><name>All Staff Computers</name><is_smart>false</is_smart>
    <computers><computer><id>103</id><name>Mac-03</name></computer></computers>
</computer_group>"""

    responses = [_mock_response(200, source_xml), _mock_response(200, target_xml)]
    with patch("resolver.classic_get", side_effect=responses):
        resolved, errors = resolver.resolve(entries, token, session)

    assert errors == []
    assert len(resolved) == 1
    rm = resolved[0]
    assert rm.source_id == 1
    assert rm.target_id == 5
    assert rm.delta == [101, 102]
    assert rm.already_present == []


def test_resolve_rejects_smart_target():
    entries = [
        {"source": "Old Group", "target": "Smart Target", "type": "computer"}
    ]
    token = _make_token()
    session = MagicMock()

    source_xml = COMPUTER_GROUP_XML
    smart_target_xml = SMART_COMPUTER_GROUP_XML  # id=2, is_smart=true

    responses = [_mock_response(200, source_xml), _mock_response(200, smart_target_xml)]
    with patch("resolver.classic_get", side_effect=responses):
        resolved, errors = resolver.resolve(entries, token, session)

    assert resolved == []
    assert len(errors) == 1
    assert "smart" in errors[0].message.lower()


def test_resolve_rejects_missing_source():
    entries = [
        {"source": "Ghost Group", "target": "All Staff Computers", "type": "computer"}
    ]
    token = _make_token()
    session = MagicMock()

    responses = [_mock_response(404), _mock_response(200, COMPUTER_GROUP_XML)]
    with patch("resolver.classic_get", side_effect=responses):
        resolved, errors = resolver.resolve(entries, token, session)

    assert any("source" in e.message.lower() or "not found" in e.message.lower() for e in errors)


def test_resolve_rejects_same_group():
    entries = [
        {"source": 1, "target": 1, "type": "computer"}
    ]
    token = _make_token()
    session = MagicMock()

    with patch("resolver.classic_get", return_value=_mock_response(200, COMPUTER_GROUP_XML)):
        resolved, errors = resolver.resolve(entries, token, session)

    assert any("same" in e.message.lower() for e in errors)


def test_resolve_delta_excludes_already_present():
    entries = [
        {"source": "Old Group", "target": "New Group", "type": "computer"}
    ]
    token = _make_token()
    session = MagicMock()

    source_xml = COMPUTER_GROUP_XML  # members=[101, 102]
    target_xml = """<?xml version="1.0" encoding="UTF-8"?>
<computer_group>
    <id>5</id><name>New Group</name><is_smart>false</is_smart>
    <computers><computer><id>101</id><name>Mac-01</name></computer></computers>
</computer_group>"""

    responses = [_mock_response(200, source_xml), _mock_response(200, target_xml)]
    with patch("resolver.classic_get", side_effect=responses):
        resolved, errors = resolver.resolve(entries, token, session)

    assert errors == []
    rm = resolved[0]
    assert rm.delta == [102]
    assert rm.already_present == [101]


def test_resolve_collects_all_errors():
    entries = [
        {"source": "Ghost", "target": "All Macs", "type": "computer"},
        {"source": "Old Group", "target": "Smart Target", "type": "computer"},
    ]
    token = _make_token()
    session = MagicMock()

    responses = [
        _mock_response(404),                    # Ghost not found
        _mock_response(200, COMPUTER_GROUP_XML), # All Macs (target for entry 1)
        _mock_response(200, COMPUTER_GROUP_XML), # Old Group (source for entry 2)
        _mock_response(200, SMART_COMPUTER_GROUP_XML),  # Smart Target (target for entry 2)
    ]
    with patch("resolver.classic_get", side_effect=responses):
        resolved, errors = resolver.resolve(entries, token, session)

    assert len(errors) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_resolver.py -v
```

Expected: failures on the new tests (functions not defined yet).

- [ ] **Step 3: Implement `_lookup_group` and `resolve` in `resolver.py`**

Append to `resolver.py`:

```python
from urllib.parse import quote
from api import classic_get


def _lookup_group(ref, group_type, token, session):
    if group_type == "computer":
        base = "/JSSResource/computergroups"
    else:
        base = "/JSSResource/mobiledevicegroups"

    if isinstance(ref, int):
        path = f"{base}/id/{ref}"
    else:
        path = f"{base}/name/{quote(str(ref), safe='')}"

    response = classic_get(path, token, session)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return _parse_group_xml(response.text, group_type)


def resolve(entries, token, session):
    resolved = []
    errors = []

    for i, entry in enumerate(entries):
        source_ref = entry["source"]
        target_ref = entry["target"]
        group_type = entry["type"]

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

        if target["is_smart"]:
            errors.append(ValidationError(i, f"target '{target['name']}' is a smart group — cannot add explicit members"))
            continue

        if source["id"] == target["id"]:
            errors.append(ValidationError(i, f"source and target are the same group (id={source['id']})"))
            continue

        target_member_set = set(target["members"])
        delta = [m for m in source["members"] if m not in target_member_set]
        already_present = [m for m in source["members"] if m in target_member_set]

        resolved.append(ResolvedMerge(
            source_id=source["id"],
            source_name=source["name"],
            source_is_smart=source["is_smart"],
            source_members=source["members"],
            target_id=target["id"],
            target_name=target["name"],
            target_members=target["members"],
            group_type=group_type,
            delta=delta,
            already_present=already_present,
        ))

    return resolved, errors
```

- [ ] **Step 4: Run all resolver tests**

```bash
pytest tests/test_resolver.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add resolver.py tests/test_resolver.py
git commit -m "feat: resolver lookup and resolve() with full validation"
```

---

## Task 5: `executor.py`

**Files:**
- Create: `executor.py`
- Create: `tests/test_executor.py`

**Interfaces:**
- Consumes: `ResolvedMerge` from Task 3; `classic_put`, `classic_delete` from Task 2
- Produces:
  ```python
  @dataclass
  class MergeResult:
      resolved: ResolvedMerge
      status: str          # "OK", "SKIP", or "FAIL"
      members_added: list  # list[int] of IDs actually added (empty on SKIP/FAIL)
      error: str | None    # error message on FAIL, None otherwise

  def _build_members_xml(member_ids: list[int], group_type: str) -> str
  def execute(resolved_merges: list[ResolvedMerge], token: dict, session) -> list[MergeResult]
  ```

- [ ] **Step 1: Write failing tests**

```python
# tests/test_executor.py
from unittest.mock import MagicMock, patch
from dataclasses import dataclass
import executor
from executor import MergeResult, _build_members_xml
from resolver import ResolvedMerge


def _make_token():
    return {"t": "tok", "expiration": 9999999999}


def _mock_response(status_code, text=""):
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    r.ok = status_code < 400
    return r


def _make_resolved(source_members, target_members, group_type="computer"):
    target_set = set(target_members)
    delta = [m for m in source_members if m not in target_set]
    already_present = [m for m in source_members if m in target_set]
    return ResolvedMerge(
        source_id=1, source_name="Old Group", source_is_smart=False,
        source_members=source_members,
        target_id=2, target_name="New Group",
        target_members=target_members,
        group_type=group_type,
        delta=delta,
        already_present=already_present,
    )


# ── _build_members_xml ──────────────────────────────────────────────────────

def test_build_computer_xml():
    xml = _build_members_xml([101, 102], "computer")
    assert "<computer_group>" in xml
    assert "<computer><id>101</id></computer>" in xml
    assert "<computer><id>102</id></computer>" in xml


def test_build_mobile_xml():
    xml = _build_members_xml([201], "mobile_device")
    assert "<mobile_device_group>" in xml
    assert "<mobile_device><id>201</id></mobile_device>" in xml


def test_build_empty_members():
    xml = _build_members_xml([], "computer")
    assert "<computer_group>" in xml
    assert "<computers/>" in xml or "<computers></computers>" in xml


# ── execute — SKIP ──────────────────────────────────────────────────────────

def test_execute_skip_when_no_delta():
    rm = _make_resolved([101], [101])  # source member already in target
    token = _make_token()
    session = MagicMock()

    results = executor.execute([rm], token, session)

    assert len(results) == 1
    assert results[0].status == "SKIP"
    assert results[0].members_added == []
    session.put.assert_not_called()
    session.delete.assert_not_called()


# ── execute — OK ─────────────────────────────────────────────────────────────

def test_execute_ok_adds_and_deletes():
    rm = _make_resolved([101, 102], [103])
    token = _make_token()
    session = MagicMock()

    with patch("executor.classic_put", return_value=_mock_response(201)) as mock_put, \
         patch("executor.classic_delete", return_value=_mock_response(200)) as mock_del:
        results = executor.execute([rm], token, session)

    assert results[0].status == "OK"
    assert set(results[0].members_added) == {101, 102}
    assert mock_put.called
    assert mock_del.called


# ── execute — FAIL (PUT) ─────────────────────────────────────────────────────

def test_execute_fail_retries_put_once():
    rm = _make_resolved([101], [])
    token = _make_token()
    session = MagicMock()

    with patch("executor.classic_put", return_value=_mock_response(500, "server error")) as mock_put, \
         patch("executor.classic_delete") as mock_del:
        results = executor.execute([rm], token, session)

    assert results[0].status == "FAIL"
    assert mock_put.call_count == 2  # initial + 1 retry
    mock_del.assert_not_called()


# ── execute — FAIL (DELETE) ──────────────────────────────────────────────────

def test_execute_fail_on_delete_does_not_reraise():
    rm = _make_resolved([101], [])
    token = _make_token()
    session = MagicMock()

    with patch("executor.classic_put", return_value=_mock_response(201)), \
         patch("executor.classic_delete", return_value=_mock_response(500, "delete failed")):
        results = executor.execute([rm], token, session)

    assert results[0].status == "FAIL"
    assert results[0].members_added == [101]
    assert "500" in results[0].error


# ── execute — continues after failure ────────────────────────────────────────

def test_execute_continues_after_fail():
    rm1 = _make_resolved([101], [])
    rm2 = _make_resolved([201], [])
    token = _make_token()
    session = MagicMock()

    responses_put = [_mock_response(500), _mock_response(500), _mock_response(201)]
    responses_del = [_mock_response(200)]

    with patch("executor.classic_put", side_effect=responses_put), \
         patch("executor.classic_delete", side_effect=responses_del):
        results = executor.execute([rm1, rm2], token, session)

    assert results[0].status == "FAIL"
    assert results[1].status == "OK"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_executor.py -v
```

Expected: `ImportError` — `executor` doesn't exist.

- [ ] **Step 3: Implement `executor.py`**

```python
from dataclasses import dataclass, field
from api import classic_put, classic_delete


@dataclass
class MergeResult:
    resolved: object
    status: str
    members_added: list = field(default_factory=list)
    error: str | None = None


def _build_members_xml(member_ids, group_type):
    if group_type == "computer":
        root_tag, members_tag, member_tag = "computer_group", "computers", "computer"
    else:
        root_tag, members_tag, member_tag = "mobile_device_group", "mobile_devices", "mobile_device"

    if not member_ids:
        return f"<{root_tag}><{members_tag}/></{root_tag}>"

    inner = "".join(f"<{member_tag}><id>{mid}</id></{member_tag}>" for mid in member_ids)
    return f"<{root_tag}><{members_tag}>{inner}</{members_tag}></{root_tag}>"


def execute(resolved_merges, token, session):
    results = []
    for rm in resolved_merges:
        if not rm.delta:
            results.append(MergeResult(resolved=rm, status="SKIP"))
            continue

        if rm.group_type == "computer":
            put_path = f"/JSSResource/computergroups/id/{rm.target_id}"
            del_path = f"/JSSResource/computergroups/id/{rm.source_id}"
        else:
            put_path = f"/JSSResource/mobiledevicegroups/id/{rm.target_id}"
            del_path = f"/JSSResource/mobiledevicegroups/id/{rm.source_id}"

        new_members = rm.target_members + rm.delta
        xml_body = _build_members_xml(new_members, rm.group_type)

        put_response = None
        for _ in range(2):
            put_response = classic_put(put_path, xml_body, token, session)
            if put_response.ok:
                break

        if not put_response.ok:
            results.append(MergeResult(
                resolved=rm, status="FAIL",
                error=f"PUT {put_response.status_code}: {put_response.text[:200]}",
            ))
            continue

        del_response = classic_delete(del_path, token, session)
        if not del_response.ok:
            results.append(MergeResult(
                resolved=rm, status="FAIL", members_added=rm.delta,
                error=f"DELETE {del_response.status_code}: {del_response.text[:200]}",
            ))
        else:
            results.append(MergeResult(resolved=rm, status="OK", members_added=rm.delta))

    return results
```

- [ ] **Step 4: Run all executor tests**

```bash
pytest tests/test_executor.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add executor.py tests/test_executor.py
git commit -m "feat: executor with PUT/DELETE and retry logic"
```

---

## Task 6: `reporter.py`

**Files:**
- Create: `reporter.py`
- Create: `tests/test_reporter.py`

**Interfaces:**
- Consumes: `ResolvedMerge` from Task 3; `MergeResult` from Task 5
- Produces:
  ```python
  def print_dry_run(resolved_merges: list[ResolvedMerge]) -> None
  def print_results(results: list[MergeResult]) -> None
  def write_log(results: list[MergeResult], log_path: str) -> None
  ```

- [ ] **Step 1: Write failing tests**

```python
# tests/test_reporter.py
import os
import reporter
from resolver import ResolvedMerge
from executor import MergeResult


def _make_resolved(source_name="Old Group", target_name="New Group",
                   source_is_smart=False, group_type="computer",
                   delta=None, already_present=None, target_members=None):
    delta = delta or [101, 102]
    already_present = already_present or []
    target_members = target_members or []
    return ResolvedMerge(
        source_id=1, source_name=source_name, source_is_smart=source_is_smart,
        source_members=delta + already_present,
        target_id=2, target_name=target_name, target_members=target_members,
        group_type=group_type, delta=delta, already_present=already_present,
    )


def _make_result(status, members_added=None, error=None, **resolved_kwargs):
    return MergeResult(
        resolved=_make_resolved(**resolved_kwargs),
        status=status,
        members_added=members_added or [],
        error=error,
    )


# ── print_dry_run ────────────────────────────────────────────────────────────

def test_dry_run_prints_source_and_target(capsys):
    resolved = [_make_resolved(source_name="Old Group", target_name="New Group")]
    reporter.print_dry_run(resolved)
    out = capsys.readouterr().out
    assert "Old Group" in out
    assert "New Group" in out


def test_dry_run_prints_member_counts(capsys):
    resolved = [_make_resolved(delta=[101, 102], already_present=[103])]
    reporter.print_dry_run(resolved)
    out = capsys.readouterr().out
    assert "2" in out  # delta count
    assert "1" in out  # already_present count


def test_dry_run_shows_smart_label(capsys):
    resolved = [_make_resolved(source_is_smart=True)]
    reporter.print_dry_run(resolved)
    out = capsys.readouterr().out
    assert "smart" in out.lower()


# ── print_results ────────────────────────────────────────────────────────────

def test_results_shows_ok(capsys):
    results = [_make_result("OK", members_added=[101, 102])]
    reporter.print_results(results)
    out = capsys.readouterr().out
    assert "[OK]" in out
    assert "2" in out


def test_results_shows_skip(capsys):
    results = [_make_result("SKIP")]
    reporter.print_results(results)
    out = capsys.readouterr().out
    assert "[SKIP]" in out


def test_results_shows_fail_with_error(capsys):
    results = [_make_result("FAIL", error="PUT 500: server error")]
    reporter.print_results(results)
    out = capsys.readouterr().out
    assert "[FAIL]" in out
    assert "500" in out


def test_results_summary_counts(capsys):
    results = [
        _make_result("OK", members_added=[101]),
        _make_result("SKIP"),
        _make_result("FAIL", error="err"),
    ]
    reporter.print_results(results)
    out = capsys.readouterr().out
    assert "1 succeeded" in out
    assert "1 skipped" in out
    assert "1 failed" in out


# ── write_log ────────────────────────────────────────────────────────────────

def test_write_log_creates_file(tmp_path):
    log_path = str(tmp_path / "test.log")
    results = [_make_result("OK", members_added=[101])]
    reporter.write_log(results, log_path)
    assert os.path.exists(log_path)


def test_write_log_contains_status(tmp_path):
    log_path = str(tmp_path / "test.log")
    results = [_make_result("OK", members_added=[101, 102])]
    reporter.write_log(results, log_path)
    content = open(log_path).read()
    assert "OK" in content
    assert "Old Group" in content


def test_write_log_records_errors(tmp_path):
    log_path = str(tmp_path / "test.log")
    results = [_make_result("FAIL", error="PUT 500: oops")]
    reporter.write_log(results, log_path)
    content = open(log_path).read()
    assert "PUT 500" in content
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_reporter.py -v
```

Expected: `ImportError` — `reporter` doesn't exist.

- [ ] **Step 3: Implement `reporter.py`**

```python
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
```

- [ ] **Step 4: Run all reporter tests**

```bash
pytest tests/test_reporter.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Run full test suite**

```bash
pytest -v
```

Expected: all tests pass across all test files.

- [ ] **Step 6: Commit**

```bash
git add reporter.py tests/test_reporter.py
git commit -m "feat: reporter — dry-run output, result summary, log writing"
```

---

## Task 7: `run.py` — Integration

**Files:**
- Create: `run.py`

**Interfaces:**
- Consumes: `resolve` (Task 4), `execute` (Task 5), `print_dry_run`, `print_results`, `write_log` (Task 6)
- Produces: executable entry point; no new importable symbols

No unit tests for `run.py` — it is pure orchestration glue. Verify via a dry-run smoke test against a real or stubbed `merge.yaml`.

- [ ] **Step 1: Implement `run.py`**

```python
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

    config_path = os.path.join(os.path.dirname(__file__), "merge.yaml")
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
```

- [ ] **Step 2: Create a minimal `merge.yaml` for smoke testing**

```yaml
merges:
  - source: "REPLACE WITH A REAL SOURCE GROUP NAME"
    target: "REPLACE WITH A REAL TARGET GROUP NAME"
    type: computer
```

(Do not commit this — it is gitignored.)

- [ ] **Step 3: Run dry-run smoke test**

Ensure `.env` exists with `JAMF_URL`, `CLIENT_ID`, `CLIENT_SECRET`, then:

```bash
source .venv/bin/activate
python run.py --dry
```

Expected: validation output or dry-run plan printed. No writes made.

- [ ] **Step 4: Run full test suite one final time**

```bash
pytest -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add run.py
git commit -m "feat: run.py integration — wire resolve/execute/report with token lifecycle"
```

---

## Self-Review

**Spec coverage check:**
- [x] YAML config with source/target/type — Task 1 (example) + Task 7 (loading)
- [x] Name or ID lookup — Task 4 (`_lookup_group`)
- [x] Smart group member snapshot — Task 4 (`resolve` captures all members regardless of is_smart)
- [x] Smart target rejection — Task 4 (validation in `resolve`)
- [x] Source == target rejection — Task 4 (validation)
- [x] `--dry` flag — Task 7 (`argparse`) + Task 6 (`print_dry_run`)
- [x] Delta computation (exclude already-present) — Task 4 + Task 5
- [x] PUT with one retry — Task 5 (`execute` loop)
- [x] Delete only on success — Task 5
- [x] SKIP when delta is empty — Task 5
- [x] Per-entry result + summary — Task 6 (`print_results`)
- [x] Log writing to `logs/` — Task 6 (`write_log`) + Task 1 (`run.sh` sets `LOG_FILE`)
- [x] Log rotation (last 8) — Task 1 (`run.sh`)
- [x] Both computer and mobile device groups — Tasks 3–5 (group_type branching throughout)
- [x] Token lifecycle (get + invalidate) — Task 7 (`run.py`)

**No placeholders found.** All steps contain complete code.

**Type consistency verified:** `ResolvedMerge` defined in Task 3, consumed identically in Tasks 4, 5, 6. `MergeResult` defined in Task 5, consumed identically in Task 6. `classic_get/put/delete` signatures match across Tasks 2, 4, 5.
