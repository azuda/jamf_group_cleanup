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
