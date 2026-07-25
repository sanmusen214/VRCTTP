import json

import pytest

from core.engine import PipelineEngine, _validate_singleton_modules
from modules.consumer.desktop_overlay import DesktopOverlayService


class _FakeOverlayService:
    def __init__(self) -> None:
        self.started_with: list[dict] = []
        self.stop_count = 0
        self.ensure_visible_results: list[dict] = []

    def start(self, config: dict) -> None:
        self.started_with.append(config)

    def stop(self) -> None:
        self.stop_count += 1

    def ensure_visible(self, config: dict) -> bool:
        self.ensure_visible_results.append(config)
        return True


def test_rejects_multiple_desktop_overlay_definitions() -> None:
    config = {
        "modules": {
            "overlay_a": {"type": "desktop_overlay"},
            "overlay_b": {"type": "desktop_overlay"},
        }
    }

    with pytest.raises(ValueError, match="最多只能存在一个"):
        _validate_singleton_modules(config)


def test_overlay_service_outlives_pipeline_stop(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "modules": {
                    "overlay": {
                        "type": "desktop_overlay",
                        "params": {"opacity": 0.6},
                    }
                },
                "pipelines": [],
            }
        ),
        encoding="utf-8",
    )
    service = _FakeOverlayService()
    monkeypatch.setattr(
        DesktopOverlayService,
        "instance",
        classmethod(lambda cls: service),
    )
    engine = PipelineEngine(str(config_path))
    engine.load_config()

    engine.start_all()
    engine.stop_all()

    assert service.started_with == [{"opacity": 0.6}]
    assert service.stop_count == 0
    assert engine.ensure_desktop_overlay_visible() is True
    assert service.ensure_visible_results == [{"opacity": 0.6}]

    engine.shutdown()
    assert service.stop_count == 1


def test_reload_reconfigures_without_stopping_overlay(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config = {
        "modules": {
            "overlay": {
                "type": "desktop_overlay",
                "params": {"font_size": 18},
            }
        },
        "pipelines": [],
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    service = _FakeOverlayService()
    monkeypatch.setattr(
        DesktopOverlayService,
        "instance",
        classmethod(lambda cls: service),
    )
    engine = PipelineEngine(str(config_path))
    engine.load_config()
    engine.start_all()

    config["modules"]["overlay"]["params"]["font_size"] = 26
    config_path.write_text(json.dumps(config), encoding="utf-8")
    engine.reload_config()

    assert service.started_with == [{"font_size": 18}, {"font_size": 26}]
    assert service.stop_count == 0
