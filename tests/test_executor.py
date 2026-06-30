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


FRESH_TARGET_XML = """<?xml version="1.0" encoding="UTF-8"?>
<computer_group>
    <id>2</id><name>New Group</name><is_smart>false</is_smart>
    <computers><computer><id>103</id><name>Mac-03</name></computer></computers>
</computer_group>"""

EMPTY_TARGET_XML = """<?xml version="1.0" encoding="UTF-8"?>
<computer_group>
    <id>2</id><name>New Group</name><is_smart>false</is_smart>
    <computers/>
</computer_group>"""


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

    with patch("executor.classic_get", return_value=_mock_response(200, FRESH_TARGET_XML)), \
         patch("executor.put_with_retry", return_value=_mock_response(201)) as mock_put, \
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

    with patch("executor.classic_get", return_value=_mock_response(200, EMPTY_TARGET_XML)), \
         patch("api.classic_put", return_value=_mock_response(500, "server error")) as mock_put, \
         patch("executor.classic_delete") as mock_del:
        results = executor.execute([rm], token, session)

    assert results[0].status == "FAIL"
    assert mock_put.call_count == 2  # initial + 1 retry inside put_with_retry
    mock_del.assert_not_called()


# ── execute — FAIL (DELETE) ──────────────────────────────────────────────────

def test_execute_fail_on_delete_does_not_reraise():
    rm = _make_resolved([101], [])
    token = _make_token()
    session = MagicMock()

    with patch("executor.classic_get", return_value=_mock_response(200, EMPTY_TARGET_XML)), \
         patch("executor.put_with_retry", return_value=_mock_response(201)), \
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

    responses_get = [_mock_response(200, EMPTY_TARGET_XML), _mock_response(200, EMPTY_TARGET_XML)]
    responses_put = [_mock_response(500), _mock_response(500), _mock_response(201)]
    responses_del = [_mock_response(200)]

    with patch("executor.classic_get", side_effect=responses_get), \
         patch("api.classic_put", side_effect=responses_put), \
         patch("executor.classic_delete", side_effect=responses_del):
        results = executor.execute([rm1, rm2], token, session)

    assert results[0].status == "FAIL"
    assert results[1].status == "OK"
