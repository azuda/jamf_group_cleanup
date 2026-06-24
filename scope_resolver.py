from dataclasses import dataclass, field
import sys
import xml.etree.ElementTree as ET
from urllib.parse import quote
from api import classic_get
from resolver import _parse_group_xml, ValidationError


@dataclass
class ScopedObject:
    object_id: int
    object_name: str
    object_type: str          # "policy", "osx_profile", "mobile_profile"
    in_inclusions: bool
    in_exclusions: bool
    target_already_present: bool = False


@dataclass
class ResolvedScope:
    source_id: int
    source_name: str
    target_id: int
    target_name: str
    group_type: str            # "computer" or "mobile_device"
    objects: list = field(default_factory=list)


OBJECT_TYPE_SPECS = {
    "computer": [
        {
            "object_type": "policy",
            "list_path": "/JSSResource/policies",
            "list_tag": "policy",
            "detail_template": "/JSSResource/policies/id/{}",
            "include_path": "scope/computer_groups/computer_group",
            "exclude_path": "scope/exclusions/computer_groups/computer_group",
        },
        {
            "object_type": "osx_profile",
            "list_path": "/JSSResource/osxconfigurationprofiles",
            "list_tag": "os_x_configuration_profile",
            "detail_template": "/JSSResource/osxconfigurationprofiles/id/{}",
            "include_path": "scope/computer_groups/computer_group",
            "exclude_path": "scope/exclusions/computer_groups/computer_group",
        },
    ],
    "mobile_device": [
        {
            "object_type": "mobile_profile",
            "list_path": "/JSSResource/mobiledeviceconfigurationprofiles",
            "list_tag": "configuration_profile",
            "detail_template": "/JSSResource/mobiledeviceconfigurationprofiles/id/{}",
            "include_path": "scope/mobile_device_groups/mobile_device_group",
            "exclude_path": "scope/exclusions/mobile_device_groups/mobile_device_group",
        },
    ],
}


def _parse_ids_from_list_xml(xml_text, item_tag):
    root = ET.fromstring(xml_text)
    return [int(el.findtext("id")) for el in root.findall(item_tag)]


def _check_object_for_group(xml_text, source_id, target_id, include_path, exclude_path):
    root = ET.fromstring(xml_text)
    in_inc = False
    in_exc = False
    target_present = False

    for el in root.findall(include_path):
        gid = int(el.findtext("id") or 0)
        if gid == source_id:
            in_inc = True
        if gid == target_id:
            target_present = True

    for el in root.findall(exclude_path):
        gid = int(el.findtext("id") or 0)
        if gid == source_id:
            in_exc = True
        if gid == target_id:
            target_present = True

    return in_inc, in_exc, target_present


def _lookup_group(ref, group_type, token, session):
    if group_type == "computer":
        base = "/JSSResource/computergroups"
    else:
        base = "/JSSResource/mobiledevicegroups"

    if isinstance(ref, int):
        path = f"{base}/id/{ref}"
    else:
        path = f"{base}/name/{quote(str(ref), safe='')}"

    response = classic_get(path, token, session)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return _parse_group_xml(response.text, group_type)


def _scan_object_type(spec, source_id, target_id, token, session):
    list_response = classic_get(spec["list_path"], token, session)
    list_response.raise_for_status()
    ids = _parse_ids_from_list_xml(list_response.text, spec["list_tag"])

    objects = []
    for obj_id in ids:
        detail_path = spec["detail_template"].format(obj_id)
        detail_response = classic_get(detail_path, token, session)
        if not detail_response.ok:
            print(
                f"WARNING: could not scan {spec['object_type']} id={obj_id} "
                f"({detail_response.status_code}) — skipped",
                file=sys.stderr,
            )
            continue

        in_inc, in_exc, target_present = _check_object_for_group(
            detail_response.text, source_id, target_id,
            spec["include_path"], spec["exclude_path"],
        )

        if not in_inc and not in_exc:
            continue

        root = ET.fromstring(detail_response.text)
        obj_name = root.findtext("general/name") or root.findtext("name") or ""

        objects.append(ScopedObject(
            object_id=obj_id,
            object_name=obj_name,
            object_type=spec["object_type"],
            in_inclusions=in_inc,
            in_exclusions=in_exc,
            target_already_present=target_present,
        ))

    return objects


def resolve_scope(entries, token, session):
    resolved = []
    errors = []

    for i, entry in enumerate(entries):
        source_ref = entry.get("source")
        target_ref = entry.get("target")
        group_type = entry.get("type", "")
        missing = [k for k, v in [("source", source_ref), ("target", target_ref), ("type", group_type or None)] if v is None]
        if missing:
            errors.append(ValidationError(i, f"missing required fields: {', '.join(missing)}"))
            continue

        if group_type not in ("computer", "mobile_device"):
            errors.append(ValidationError(i, f"type '{group_type}' is invalid — must be 'computer' or 'mobile_device'"))
            continue

        source = _lookup_group(source_ref, group_type, token, session)
        target = _lookup_group(target_ref, group_type, token, session)

        entry_errors = []
        if source is None:
            entry_errors.append(ValidationError(i, f"source '{source_ref}' not found"))
        if target is None:
            entry_errors.append(ValidationError(i, f"target '{target_ref}' not found"))
        if entry_errors:
            errors.extend(entry_errors)
            continue

        if source["id"] == target["id"]:
            errors.append(ValidationError(i, f"source and target are the same group (id={source['id']})"))
            continue

        all_objects = []
        for spec in OBJECT_TYPE_SPECS[group_type]:
            all_objects.extend(_scan_object_type(spec, source["id"], target["id"], token, session))

        resolved.append(ResolvedScope(
            source_id=source["id"],
            source_name=source["name"],
            target_id=target["id"],
            target_name=target["name"],
            group_type=group_type,
            objects=all_objects,
        ))

    return resolved, errors
