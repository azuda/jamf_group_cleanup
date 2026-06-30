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
