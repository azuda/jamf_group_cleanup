from dataclasses import dataclass, field
import xml.etree.ElementTree as ET


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
