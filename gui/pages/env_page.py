"""
环境变量编辑页面 — 读写项目根目录的 .env 文件。

注意：修改 .env 后需重启服务才能让引擎感知（${VAR} 替换在启动时完成）。
"""
from __future__ import annotations

import os
from nicegui import ui

import gui.state as state
from gui.components.nav import create_nav

# .env 文件路径
_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
_SENSITIVE_KEYWORDS = ("key", "secret", "token", "password", "pass", "pwd")


def _is_sensitive(key: str) -> bool:
    k = key.lower()
    return any(w in k for w in _SENSITIVE_KEYWORDS)


def _read_env_file(path: str) -> tuple[list[str], list[tuple[str, str]]]:
    """
    解析 .env 文件。
    返回 (header_lines, kv_pairs)：
      - header_lines: 注释行和空行（原样保留，写回时输出在 KV 之前）
      - kv_pairs: 所有 KEY=VALUE 行，保持顺序
    """
    header_lines: list[str] = []
    kv_pairs: list[tuple[str, str]] = []

    if not os.path.exists(path):
        return [], []

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.rstrip("\n")
            if stripped.strip().startswith("#") or stripped.strip() == "":
                header_lines.append(stripped)
            elif "=" in stripped:
                key, _, value = stripped.partition("=")
                kv_pairs.append((key.strip(), value.strip()))
            else:
                header_lines.append(stripped)

    return header_lines, kv_pairs


def _write_env_file(path: str, header_lines: list[str], kv_pairs: list[tuple[str, str]]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for line in header_lines:
            f.write(line + "\n")
        if header_lines and kv_pairs and header_lines[-1].strip() != "":
            f.write("\n")
        for key, value in kv_pairs:
            f.write(f"{key}={value}\n")


def _apply_env_to_process(
    old_pairs: list[tuple[str, str]],
    new_pairs: list[tuple[str, str]],
) -> None:
    """Apply .env edits to the current process so config reload can see them."""
    old_values = {key: value for key, value in old_pairs}
    new_values = {key: value for key, value in new_pairs}

    for key, value in new_values.items():
        os.environ[key] = value

    for key, old_value in old_values.items():
        if key in new_values:
            continue
        if os.environ.get(key) == old_value:
            os.environ.pop(key, None)


def register(app) -> None:  # noqa: ARG001

    @ui.page("/env")
    def env_page() -> None:
        ui.page_title("环境变量")
        create_nav()
        engine = state.get_engine()

        env_path = os.path.abspath(_ENV_PATH)
        header_lines, kv_pairs = _read_env_file(env_path)

        # kv_list: mutable list of [key, value] — source of truth for the editor
        kv_list: list[list[str]] = [[k, v] for k, v in kv_pairs]

        with ui.column().classes("w-full max-w-3xl mx-auto q-pa-md gap-4"):
            ui.label("环境变量编辑").classes("text-h5")
            ui.label(f"文件路径: {env_path}").classes("text-caption text-grey font-mono")
            ui.label(
                "保存后会立即写入当前进程环境变量，并热重载配置让 ${VAR} 占位符生效。"
            ).classes("text-caption text-grey")

            ui.separator()

            @ui.refreshable
            def kv_editor() -> None:
                if not kv_list:
                    ui.label("暂无变量，点击下方「添加变量」新增。").classes("text-grey")
                    return
                for i, pair in enumerate(kv_list):
                    key = pair[0]
                    sensitive = _is_sensitive(key)
                    with ui.row().classes("items-center w-full gap-2"):
                        ui.label(key).classes("text-caption text-bold font-mono").style(
                            "min-width:180px; word-break:break-all"
                        )

                        def _make_on_change(idx: int):
                            def _on_change(e) -> None:
                                kv_list[idx][1] = e.value
                            return _on_change

                        ui.input(
                            value=pair[1],
                            password=sensitive,
                            password_toggle_button=sensitive,
                            on_change=_make_on_change(i),
                        ).classes("flex-grow").style("min-width:200px")

                        def _make_delete(idx: int):
                            def _delete() -> None:
                                kv_list.pop(idx)
                                kv_editor.refresh()
                            return _delete

                        ui.button(
                            icon="delete", color="negative", on_click=_make_delete(i)
                        ).props("flat round dense")

            kv_editor()

            ui.separator()
            ui.label("添加变量").classes("text-subtitle2")

            with ui.row().classes("items-end gap-2 w-full"):
                new_key = ui.input(label="KEY（变量名）").style("min-width:160px")
                new_val = ui.input(label="VALUE（初始值）").classes("flex-grow").style("min-width:200px")

                def _add_var() -> None:
                    k = new_key.value.strip()
                    v = new_val.value.strip()
                    if not k:
                        ui.notify("变量名不能为空", type="warning")
                        return
                    if any(row[0] == k for row in kv_list):
                        ui.notify(f"变量 {k!r} 已存在", type="warning")
                        return
                    kv_list.append([k, v])
                    new_key.value = ""
                    new_val.value = ""
                    kv_editor.refresh()

                ui.button("添加", icon="add", on_click=_add_var)

            ui.separator()

            def _save() -> None:
                try:
                    new_pairs = [(row[0], row[1]) for row in kv_list]
                    _write_env_file(env_path, header_lines, new_pairs)
                    _apply_env_to_process(kv_pairs, new_pairs)
                    engine.reload_config()
                    kv_pairs[:] = new_pairs
                    ui.notify("已保存到 .env，并已应用到当前运行配置", type="positive")
                except Exception as exc:
                    ui.notify(f"保存失败: {exc}", type="negative")

            ui.button("保存并应用 .env", icon="save", color="primary", on_click=_save)

