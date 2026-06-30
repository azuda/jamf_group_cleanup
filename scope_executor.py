import sys
from dataclasses import dataclass, field
import xml.etree.ElementTree as ET
from api import classic_get, put_with_retry
from scope_resolver import ResolvedScope, ScopedObject, SmartGroupCriterionRef, _check_object_for_group, SMART_CRITERION_NAME


@dataclass
class ScopeResult:
  resolved: ResolvedScope
  status: str
  objects_updated: list = field(default_factory=list)
  smart_groups_updated: list = field(default_factory=list)
  error: str | None = None
  skip_reason: str | None = None


DETAIL_PATH_BY_TYPE = {
  "policy": "/JSSResource/policies/id/{}",
  "osx_profile": "/JSSResource/osxconfigurationprofiles/id/{}",
  "mobile_profile": "/JSSResource/mobiledeviceconfigurationprofiles/id/{}",
  "mobile_app": "/JSSResource/mobiledeviceapps/id/{}",
}

INCLUDE_PATH_BY_GROUP_TYPE = {
  "computer": "scope/computer_groups/computer_group",
  "mobile_device": "scope/mobile_device_groups/mobile_device_group",
}

EXCLUDE_PATH_BY_GROUP_TYPE = {
  "computer": "scope/exclusions/computer_groups/computer_group",
  "mobile_device": "scope/exclusions/mobile_device_groups/mobile_device_group",
}

SMART_GROUP_PUT_PATH = {
  "computer": "/JSSResource/computergroups/id/{}",
  "mobile_device": "/JSSResource/mobiledevicegroups/id/{}",
}


def _replace_group_in_xml(xml_text, source_id, target_id, target_name, include_path, exclude_path, in_inclusions, in_exclusions):
  root = ET.fromstring(xml_text)

  if in_inclusions:
    for el in root.findall(include_path):
      if int(el.findtext("id") or 0) == source_id:
        el.find("id").text = str(target_id)
        el.find("name").text = target_name

  if in_exclusions:
    for el in root.findall(exclude_path):
      if int(el.findtext("id") or 0) == source_id:
        el.find("id").text = str(target_id)
        el.find("name").text = target_name

  return ET.tostring(root, encoding="unicode")


def _replace_criterion_value(xml_text, criterion_name, source_name, target_name):
  root = ET.fromstring(xml_text)
  for el in root.findall("criteria/criterion"):
    if el.findtext("name") == criterion_name and el.findtext("value") == source_name:
      el.find("value").text = target_name
  return ET.tostring(root, encoding="unicode")


def _source_criterion_present(xml_text, criterion_name, source_name):
  root = ET.fromstring(xml_text)
  return any(
    el.findtext("name") == criterion_name and el.findtext("value") == source_name
    for el in root.findall("criteria/criterion")
  )


def execute_scope(resolved_scopes, token, session):
  results = []
  for rs in resolved_scopes:
    actionable = [obj for obj in rs.objects if not obj.target_already_present]
    actionable_sg = [sg for sg in rs.smart_groups if not sg.target_already_present]

    if not actionable and not actionable_sg:
      reason = "all_noop" if (rs.objects or rs.smart_groups) else "no_references"
      results.append(ScopeResult(resolved=rs, status="SKIP", skip_reason=reason))
      continue

    include_path = INCLUDE_PATH_BY_GROUP_TYPE[rs.group_type]
    exclude_path = EXCLUDE_PATH_BY_GROUP_TYPE[rs.group_type]
    criterion_name = SMART_CRITERION_NAME[rs.group_type]
    objects_updated = []
    smart_groups_updated = []
    failed = False
    fail_errors = []

    for obj in actionable:
      put_path = DETAIL_PATH_BY_TYPE[obj.object_type].format(obj.object_id)

      get_response = classic_get(put_path, token, session)
      if not get_response.ok:
        failed = True
        fail_errors.append(f"GET '{obj.object_name}' {get_response.status_code}: {get_response.text[:200]}")
        continue

      fresh_inc, fresh_exc, fresh_target_present = _check_object_for_group(
        get_response.text, rs.source_id, rs.target_id, include_path, exclude_path
      )
      if fresh_target_present:
        continue

      updated_xml = _replace_group_in_xml(
        get_response.text, rs.source_id, rs.target_id, rs.target_name,
        include_path, exclude_path, fresh_inc, fresh_exc,
      )

      put_response = put_with_retry(put_path, updated_xml, token, session)

      if not put_response.ok:
        verify_response = classic_get(put_path, token, session)
        if verify_response.ok:
          v_inc, v_exc, _ = _check_object_for_group(
            verify_response.text, rs.source_id, rs.target_id, include_path, exclude_path
          )
          if not v_inc and not v_exc:
            print(
              f"  WARNING: PUT '{obj.object_name}' returned {put_response.status_code} "
              f"but scope change applied — Jamf reported: {put_response.text[:120]}",
              file=sys.stderr,
            )
            objects_updated.append(obj)
            continue
        failed = True
        fail_errors.append(f"PUT '{obj.object_name}' {put_response.status_code}: {put_response.text[:200]}")
      else:
        objects_updated.append(obj)

    for sg in actionable_sg:
      put_path = SMART_GROUP_PUT_PATH[rs.group_type].format(sg.group_id)

      get_response = classic_get(put_path, token, session)
      if not get_response.ok:
        failed = True
        fail_errors.append(f"GET smart group '{sg.group_name}' {get_response.status_code}: {get_response.text[:200]}")
        continue

      if not _source_criterion_present(get_response.text, criterion_name, rs.source_name):
        continue  # another admin already updated it

      updated_xml = _replace_criterion_value(get_response.text, criterion_name, rs.source_name, rs.target_name)

      put_response = put_with_retry(put_path, updated_xml, token, session)

      if not put_response.ok:
        verify_response = classic_get(put_path, token, session)
        if verify_response.ok and not _source_criterion_present(verify_response.text, criterion_name, rs.source_name):
          print(
            f"  WARNING: PUT smart group '{sg.group_name}' returned {put_response.status_code} "
            f"but criterion change applied — Jamf reported: {put_response.text[:120]}",
            file=sys.stderr,
          )
          smart_groups_updated.append(sg)
          continue
        failed = True
        fail_errors.append(f"PUT smart group '{sg.group_name}' {put_response.status_code}: {put_response.text[:200]}")
      else:
        smart_groups_updated.append(sg)

    if failed:
      results.append(ScopeResult(
        resolved=rs, status="FAIL",
        objects_updated=objects_updated,
        smart_groups_updated=smart_groups_updated,
        error="; ".join(fail_errors),
      ))
    else:
      results.append(ScopeResult(
        resolved=rs, status="OK",
        objects_updated=objects_updated,
        smart_groups_updated=smart_groups_updated,
      ))

  return results
