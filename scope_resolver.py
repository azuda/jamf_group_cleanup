from dataclasses import dataclass, field
import xml.etree.ElementTree as ET
from urllib.parse import quote
from api import classic_get
from resolver import _lookup_group, ValidationError


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
