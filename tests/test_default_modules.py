from core.default_modules import (
    DEFAULT_MODULES,
    ensure_default_modules,
)


def test_adds_default_desktop_overlay_when_missing() -> None:
    config = {"modules": {"terminal": {"type": "terminal"}}}

    assert ensure_default_modules(config) is True
    overlays = [
        definition
        for definition in config["modules"].values()
        if definition.get("type") == "desktop_overlay"
    ]
    assert overlays == [DEFAULT_MODULES[0]["definition"]]
    assert (
        overlays[0]["params"]["group_by"]
        == "timestamp_中间件-GUI输入文字"
    )


def test_keeps_existing_desktop_overlay_unchanged() -> None:
    existing = {
        "type": "desktop_overlay",
        "params": {"opacity": 0.4, "group_by": "custom_group"},
    }
    config = {"modules": {"custom_overlay": existing}}

    assert ensure_default_modules(config) is False
    assert config["modules"] == {"custom_overlay": existing}


def test_default_definition_is_copied() -> None:
    first = {"modules": {}}
    second = {"modules": {}}
    ensure_default_modules(first)
    ensure_default_modules(second)

    first_overlay = next(iter(first["modules"].values()))
    first_overlay["params"]["opacity"] = 0.2

    second_overlay = next(iter(second["modules"].values()))
    assert second_overlay["params"]["opacity"] == 0.78


def test_generic_list_can_add_multiple_default_modules() -> None:
    defaults = [
        {
            "ref_id": "output_a",
            "match": {"type": "output_a"},
            "definition": {"type": "output_a", "params": {"enabled": True}},
        },
        {
            "ref_id": "output_b",
            "match": {"type": "output_b"},
            "definition": {"type": "output_b", "params": {}},
        },
    ]
    config = {"modules": {}}

    assert ensure_default_modules(config, defaults) is True
    assert set(config["modules"]) == {"output_a", "output_b"}
    assert ensure_default_modules(config, defaults) is False


def test_match_can_use_more_than_module_type() -> None:
    defaults = [
        {
            "ref_id": "special_terminal",
            "match": {"type": "terminal", "display_name": "内建终端"},
            "definition": {
                "type": "terminal",
                "display_name": "内建终端",
                "params": {},
            },
        }
    ]
    config = {
        "modules": {
            "user_terminal": {
                "type": "terminal",
                "display_name": "用户终端",
                "params": {},
            }
        }
    }

    assert ensure_default_modules(config, defaults) is True
    assert "special_terminal" in config["modules"]
