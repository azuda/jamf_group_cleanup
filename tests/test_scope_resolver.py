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
