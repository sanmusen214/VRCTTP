from core.module_identity import (
    ensure_module_display_names,
    module_display_name,
    module_ref_id,
)


def test_module_ref_id_is_stable_and_name_based() -> None:
    assert module_ref_id("翻译到日文") == module_ref_id("翻译到日文")
    assert module_ref_id("翻译到日文") != module_ref_id("翻译到英文")
    assert module_ref_id("  翻译到日文  ") == module_ref_id("翻译到日文")
    assert module_ref_id("翻译到日文").startswith("mod_")


def test_legacy_module_uses_ref_id_as_display_name() -> None:
    assert module_display_name("legacy_ref", {"type": "terminal"}) == "legacy_ref"


def test_explicit_display_name_hides_ref_id() -> None:
    config = {"display_name": "软件日志输出", "type": "terminal"}
    assert module_display_name("mod_internal", config) == "软件日志输出"


def test_legacy_config_is_augmented_without_changing_routes() -> None:
    config = {
        "modules": {"legacy_ref": {"type": "terminal", "params": {}}},
        "pipelines": [{"graph": {"entry": "legacy_ref", "routes": {}}}],
    }
    ensure_module_display_names(config)
    assert config["modules"]["legacy_ref"]["display_name"] == "legacy_ref"
    assert config["pipelines"][0]["graph"]["entry"] == "legacy_ref"
