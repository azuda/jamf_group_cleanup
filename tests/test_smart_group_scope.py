from unittest.mock import MagicMock, patch
import xml.etree.ElementTree as ET
from scope_resolver import _scan_smart_groups, SmartGroupCriterionRef, ResolvedScope
import scope_executor
from scope_executor import _replace_criterion_value, _source_criterion_present, ScopeResult


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
