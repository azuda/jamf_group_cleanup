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
