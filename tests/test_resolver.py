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
