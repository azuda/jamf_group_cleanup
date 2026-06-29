import os
from dataclasses import dataclass, field
from api import classic_get, classic_delete, put_with_retry
from pathlib import Path
from resolver import _parse_group_xml, ResolvedMerge

_DEBUG = os.environ.get("JAMF_DEBUG") == "1"
DEBUG_DIR = Path(__file__).parent / "debug"


@dataclass
class MergeResult:
  resolved: ResolvedMerge
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
      fetch_path = f"/JSSResource/computergroups/id/{rm.target_id}"
      put_path = fetch_path
      del_path = f"/JSSResource/computergroups/id/{rm.source_id}"
    else:
      fetch_path = f"/JSSResource/mobiledevicegroups/id/{rm.target_id}"
      put_path = fetch_path
      del_path = f"/JSSResource/mobiledevicegroups/id/{rm.source_id}"

    fresh_response = classic_get(fetch_path, token, session)
    if not fresh_response.ok:
      results.append(MergeResult(
        resolved=rm,
        status="FAIL",
        error=f"GET target {fresh_response.status_code}: {fresh_response.text[:200]}",
      ))
      continue

    if _DEBUG:
      DEBUG_DIR.mkdir(exist_ok=True)
      (DEBUG_DIR / f"target_{rm.target_id}.xml").write_text(fresh_response.text)

    fresh_target = _parse_group_xml(fresh_response.text, rm.group_type)
    fresh_target_members = fresh_target["members"]
    fresh_target_set = set(fresh_target_members)
    fresh_delta = [m for m in rm.source_members if m not in fresh_target_set]

    if not fresh_delta:
      results.append(MergeResult(resolved=rm, status="SKIP"))
      continue

    new_members = fresh_target_members + fresh_delta
    xml_body = _build_members_xml(new_members, rm.group_type)

    put_response = put_with_retry(put_path, xml_body, token, session)

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
        members_added=fresh_delta,
        error=f"DELETE {del_response.status_code}: {del_response.text[:200]}",
      ))
    else:
      results.append(MergeResult(resolved=rm, status="OK", members_added=fresh_delta))

  return results
