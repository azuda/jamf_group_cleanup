import resolver
from resolver import MergeConfig, ResolvedMerge, ValidationError


COMPUTER_GROUP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<computer_group>
    <id>1</id>
    <name>Staff Macs</name>
    <is_smart>false</is_smart>
    <computers>
        <computer><id>101</id><name>Mac-01</name></computer>
        <computer><id>102</id><name>Mac-02</name></computer>
    </computers>
</computer_group>"""

SMART_COMPUTER_GROUP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<computer_group>
    <id>2</id>
    <name>Smart Group</name>
    <is_smart>true</is_smart>
    <computers>
        <computer><id>201</id><name>Mac-03</name></computer>
    </computers>
</computer_group>"""

MOBILE_GROUP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<mobile_device_group>
    <id>3</id>
    <name>All iPads</name>
    <is_smart>false</is_smart>
    <mobile_devices>
        <mobile_device><id>301</id><name>iPad-01</name></mobile_device>
    </mobile_devices>
</mobile_device_group>"""

EMPTY_GROUP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<computer_group>
    <id>4</id>
    <name>Empty Group</name>
    <is_smart>false</is_smart>
    <computers/>
</computer_group>"""


def test_parse_computer_group():
    result = resolver._parse_group_xml(COMPUTER_GROUP_XML, "computer")
    assert result["id"] == 1
    assert result["name"] == "Staff Macs"
    assert result["is_smart"] is False
    assert result["members"] == [101, 102]


def test_parse_smart_computer_group():
    result = resolver._parse_group_xml(SMART_COMPUTER_GROUP_XML, "computer")
    assert result["is_smart"] is True
    assert result["members"] == [201]


def test_parse_mobile_device_group():
    result = resolver._parse_group_xml(MOBILE_GROUP_XML, "mobile_device")
    assert result["id"] == 3
    assert result["name"] == "All iPads"
    assert result["members"] == [301]


def test_parse_empty_group():
    result = resolver._parse_group_xml(EMPTY_GROUP_XML, "computer")
    assert result["members"] == []
