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

POLICY_XML_AFTER = """<?xml version="1.0" encoding="UTF-8"?>
<policy>
    <general><id>10</id><name>Deploy Software</name></general>
    <scope>
        <computer_groups>
            <computer_group><id>2</id><name>New Group</name></computer_group>
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
         patch("scope_executor.put_with_retry", return_value=_mock_response(201)):
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
    with patch("scope_executor.put_with_retry") as mock_put:
        results = scope_executor.execute_scope([rs], _make_token(), MagicMock())
    mock_put.assert_not_called()
    assert results[0].status == "SKIP"


def test_execute_scope_fail_retries_put():
    rs = _make_rs([_make_obj()])
    # PUT fails twice; verify GET returns source still in scope → true FAIL
    get_responses = [_mock_response(200, POLICY_XML), _mock_response(200, POLICY_XML)]
    with patch("scope_executor.classic_get", side_effect=get_responses), \
         patch("api.classic_put", return_value=_mock_response(500, "err")) as mock_put:
        results = scope_executor.execute_scope([rs], _make_token(), MagicMock())

    assert results[0].status == "FAIL"
    assert mock_put.call_count == 2


def test_execute_scope_put_error_but_change_applied():
    """PUT returns a non-2xx error but Jamf committed the scope change anyway."""
    rs = _make_rs([_make_obj()])
    get_responses = [
        _mock_response(200, POLICY_XML),       # initial GET — source present
        _mock_response(200, POLICY_XML_AFTER), # verify GET — source gone, change applied
    ]
    with patch("scope_executor.classic_get", side_effect=get_responses), \
         patch("scope_executor.put_with_retry", return_value=_mock_response(409, "Problem with script")):
        results = scope_executor.execute_scope([rs], _make_token(), MagicMock())

    assert results[0].status == "OK"
    assert len(results[0].objects_updated) == 1
    assert results[0].objects_updated[0].object_id == 10


def test_execute_scope_put_error_verify_get_fails():
    """PUT fails and the verify GET also fails — treat as FAIL."""
    rs = _make_rs([_make_obj()])
    get_responses = [
        _mock_response(200, POLICY_XML),  # initial GET
        _mock_response(500, "err"),        # verify GET fails
    ]
    with patch("scope_executor.classic_get", side_effect=get_responses), \
         patch("scope_executor.put_with_retry", return_value=_mock_response(409, "err")):
        results = scope_executor.execute_scope([rs], _make_token(), MagicMock())

    assert results[0].status == "FAIL"


def test_execute_scope_mobile_app_type():
    obj = ScopedObject(object_id=20, object_name="Toolbox", object_type="mobile_app",
                       in_inclusions=True, in_exclusions=False)
    rs = ResolvedScope(
        source_id=1, source_name="Old iOS Group",
        target_id=2, target_name="New iOS Group",
        group_type="mobile_device",
        objects=[obj],
    )
    app_xml = """<?xml version="1.0" encoding="UTF-8"?>
<mobile_device_application>
    <general><id>20</id><name>Toolbox</name></general>
    <scope>
        <mobile_device_groups>
            <mobile_device_group><id>1</id><name>Old iOS Group</name></mobile_device_group>
        </mobile_device_groups>
        <exclusions><mobile_device_groups/></exclusions>
    </scope>
</mobile_device_application>"""
    with patch("scope_executor.classic_get", return_value=_mock_response(200, app_xml)), \
         patch("scope_executor.put_with_retry", return_value=_mock_response(201)):
        results = scope_executor.execute_scope([rs], _make_token(), MagicMock())
    assert results[0].status == "OK"
    assert results[0].objects_updated[0].object_id == 20


def test_execute_scope_continues_after_fail():
    obj1 = ScopedObject(object_id=10, object_name="P1", object_type="policy",
                        in_inclusions=True, in_exclusions=False)
    obj2 = ScopedObject(object_id=11, object_name="P2", object_type="policy",
                        in_inclusions=True, in_exclusions=False)
    rs = _make_rs([obj1, obj2])

    # obj1: initial GET, verify GET (source still present → true FAIL); obj2: initial GET
    get_responses = [
        _mock_response(200, POLICY_XML),  # obj1 initial GET
        _mock_response(200, POLICY_XML),  # obj1 verify GET — source still there
        _mock_response(200, POLICY_XML),  # obj2 initial GET
    ]
    put_responses = [_mock_response(500), _mock_response(500), _mock_response(201)]

    with patch("scope_executor.classic_get", side_effect=get_responses), \
         patch("api.classic_put", side_effect=put_responses):
        results = scope_executor.execute_scope([rs], _make_token(), MagicMock())

    assert results[0].status == "FAIL"
    assert len(results[0].objects_updated) == 1
    assert results[0].objects_updated[0].object_id == 11
