from dataclasses import dataclass, field
import xml.etree.ElementTree as ET
from urllib.parse import quote
from api import classic_get


@dataclass
class MergeConfig:
    source: str | int
    target: str | int
    group_type: str


@dataclass
class ResolvedMerge:
    source_id: int
    source_name: str
    source_is_smart: bool
    source_members: list
    target_id: int
    target_name: str
    target_members: list
    group_type: str
    delta: list = field(default_factory=list)
    already_present: list = field(default_factory=list)


@dataclass
class ValidationError:
    index: int
    message: str


def _parse_group_xml(xml_text, group_type):
    root = ET.fromstring(xml_text)
    group_id = int(root.findtext("id"))
    name = root.findtext("name")
    is_smart = root.findtext("is_smart") == "true"

    if group_type == "computer":
        member_path = "computers/computer"
    else:
        member_path = "mobile_devices/mobile_device"

    members = [int(c.findtext("id")) for c in root.findall(member_path)]
    return {"id": group_id, "name": name, "is_smart": is_smart, "members": members}


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


def resolve(entries, token, session):
    resolved = []
    errors = []

    for i, entry in enumerate(entries):
        source_ref = entry["source"]
        target_ref = entry["target"]
        group_type = entry["type"]

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

        if target["is_smart"]:
            errors.append(ValidationError(i, f"target '{target['name']}' is a smart group — cannot add explicit members"))
            continue

        if source["id"] == target["id"]:
            errors.append(ValidationError(i, f"source and target are the same group (id={source['id']})"))
            continue

        target_member_set = set(target["members"])
        delta = [m for m in source["members"] if m not in target_member_set]
        already_present = [m for m in source["members"] if m in target_member_set]

        resolved.append(ResolvedMerge(
            source_id=source["id"],
            source_name=source["name"],
            source_is_smart=source["is_smart"],
            source_members=source["members"],
            target_id=target["id"],
            target_name=target["name"],
            target_members=target["members"],
            group_type=group_type,
            delta=delta,
            already_present=already_present,
        ))

    return resolved, errors
