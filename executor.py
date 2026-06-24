from dataclasses import dataclass, field
from api import classic_put, classic_delete


@dataclass
class MergeResult:
    resolved: object
    status: str
    members_added: list = field(default_factory=list)
    error: str | None = None


def _build_members_xml(member_ids: list, group_type: str) -> str:
    if group_type == "computer":
        root_tag, members_tag, member_tag = "computer_group", "computers", "computer"
    else:
        root_tag, members_tag, member_tag = "mobile_device_group", "mobile_devices", "mobile_device"

    if not member_ids:
        return f"<{root_tag}><{members_tag}/></{root_tag}>"

    inner = "".join(f"<{member_tag}><id>{mid}</id></{member_tag}>" for mid in member_ids)
    return f"<{root_tag}><{members_tag}>{inner}</{members_tag}></{root_tag}>"


def execute(resolved_merges: list, token: dict, session) -> list:
    results = []
    for rm in resolved_merges:
        if not rm.delta:
            results.append(MergeResult(resolved=rm, status="SKIP"))
            continue

        if rm.group_type == "computer":
            put_path = f"/JSSResource/computergroups/id/{rm.target_id}"
            del_path = f"/JSSResource/computergroups/id/{rm.source_id}"
        else:
            put_path = f"/JSSResource/mobiledevicegroups/id/{rm.target_id}"
            del_path = f"/JSSResource/mobiledevicegroups/id/{rm.source_id}"

        new_members = rm.target_members + rm.delta
        xml_body = _build_members_xml(new_members, rm.group_type)

        put_response = None
        for _ in range(2):
            put_response = classic_put(put_path, xml_body, token, session)
            if put_response.ok:
                break

        if not put_response.ok:
            results.append(MergeResult(
                resolved=rm,
                status="FAIL",
                error=f"PUT {put_response.status_code}: {put_response.text[:200]}",
            ))
            continue

        del_response = classic_delete(del_path, token, session)
        if not del_response.ok:
            results.append(MergeResult(
                resolved=rm,
                status="FAIL",
                members_added=rm.delta,
                error=f"DELETE {del_response.status_code}: {del_response.text[:200]}",
            ))
        else:
            results.append(MergeResult(resolved=rm, status="OK", members_added=rm.delta))

    return results
