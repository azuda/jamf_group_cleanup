import jamf_client


def _refresh(token):
  token["t"], token["expiration"] = jamf_client.check_token_expiration(token["t"], token["expiration"])


def classic_get(path, token, session):
  _refresh(token)
  return session.get(
    f"{jamf_client.JAMF_URL}{path}",
    headers={
      "Accept": "application/xml",
      "Authorization": f"Bearer {token['t']}",
    },
  )


def classic_put(path, xml_body, token, session):
  _refresh(token)
  return session.put(
    f"{jamf_client.JAMF_URL}{path}",
    headers={
      "Accept": "application/xml",
      "Content-Type": "application/xml",
      "Authorization": f"Bearer {token['t']}",
    },
    data=xml_body,
  )


def classic_delete(path, token, session):
  _refresh(token)
  return session.delete(
    f"{jamf_client.JAMF_URL}{path}",
    headers={
      "Authorization": f"Bearer {token['t']}",
    },
  )


def put_with_retry(path, body, token, session):
  response = classic_put(path, body, token, session)
  if not response.ok:
    response = classic_put(path, body, token, session)
  return response
