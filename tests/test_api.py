from unittest.mock import MagicMock, patch
import api


def _make_token():
    return {"t": "test-token", "expiration": 9999999999}


def test_classic_get_sets_bearer_header():
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=200)
    token = _make_token()

    with patch("jamf_client.JAMF_URL", "https://jamf.example.com"):
        with patch("jamf_client.check_token_expiration", return_value=("test-token", 9999999999)):
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

    with patch("jamf_client.JAMF_URL", "https://jamf.example.com"):
        with patch("jamf_client.check_token_expiration", return_value=("test-token", 9999999999)):
            api.classic_put("/JSSResource/computergroups/id/1", xml, token, session)

    call_kwargs = session.put.call_args
    assert call_kwargs[1]["data"] == xml
    headers = call_kwargs[1]["headers"]
    assert "application/xml" in headers["Content-Type"]


def test_classic_delete_sends_delete():
    session = MagicMock()
    session.delete.return_value = MagicMock(status_code=200)
    token = _make_token()

    with patch("jamf_client.JAMF_URL", "https://jamf.example.com"):
        with patch("jamf_client.check_token_expiration", return_value=("test-token", 9999999999)):
            api.classic_delete("/JSSResource/computergroups/id/1", token, session)

    assert session.delete.called
    call_kwargs = session.delete.call_args
    assert "Authorization" in call_kwargs[1]["headers"]
