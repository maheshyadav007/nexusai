from nexusai.modules.agent import policy


def test_every_tool_has_a_permission_section_and_sending_stands_alone() -> None:
    names = {name for name, _ in policy.SECTIONS}
    sections = {entry.name: policy.section_of(entry) for entry in policy.TOOL_ENTRIES}
    assert set(sections.values()) <= names
    assert [tool for tool, section in sections.items() if section == "Sending"] == ["send_mail"]
    assert sections["search_mail"] == sections["read_document"] == "Reading"
    assert sections["create_schedule"] == "Routines" and sections["propose_plugin"] == "Add-ons"
    assert sections["run_command"] == sections["write_file"] == "Your computer"
