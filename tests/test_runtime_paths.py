import os

import runtime_paths


def test_ensure_minimum_env_file_preserves_values_and_adds_missing(tmp_path):
    path = tmp_path / ".env"
    path.write_text("# keep\nVOLC_API_KEY=secret", encoding="utf-8")

    runtime_paths.ensure_minimum_env_file(str(path))
    content = path.read_text(encoding="utf-8")

    assert "VOLC_API_KEY=secret" in content
    for key in runtime_paths.minimum_env_key_names():
        assert content.count(f"{key}=") == 1


def test_minimum_env_metadata_groups_baidu_credentials():
    groups = runtime_paths.grouped_minimum_env_help()
    baidu = next(group for group in groups if group["keys"].startswith("BAIDU_"))

    assert baidu["keys"] == "BAIDU_APP_ID / BAIDU_APP_KEY"
    assert "百度翻译开放平台" in baidu["description"]


def test_all_minimum_env_values_empty(tmp_path):
    path = tmp_path / ".env"
    runtime_paths.ensure_minimum_env_file(str(path))
    assert runtime_paths.all_minimum_env_values_empty(str(path))

    path.write_text("VOLC_API_KEY=configured\n", encoding="utf-8")
    assert not runtime_paths.all_minimum_env_values_empty(str(path))


def test_default_config_moves_example_next_to_application(monkeypatch, tmp_path):
    template_dir = tmp_path / "tmp"
    template_dir.mkdir()
    example = template_dir / "example_config.json"
    example.write_text('{"modules": {}}', encoding="utf-8")
    monkeypatch.setattr(runtime_paths, "application_dir", lambda: os.fspath(tmp_path))

    result = runtime_paths.default_config_path()

    assert result == os.fspath(tmp_path / "config.json")
    assert (tmp_path / "config.json").read_text(encoding="utf-8") == '{"modules": {}}'
    assert not example.exists()
