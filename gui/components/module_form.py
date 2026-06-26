"""
动态模块表单组件。

根据模块类的 get_config_attributes() 生成对应的 NiceGUI 输入组件，
并提供读取当前值的工具函数。

扩展点：options_loader
  config attribute 可携带 "options_loader" 字段，值为已注册的加载器名称。
  module_form 会在渲染时调用对应加载器获取选项，并生成 ui.select 下拉菜单。
  已内置加载器：
    "microphone" — 枚举当前系统所有麦克风设备（含"系统默认"空选项）
"""
from __future__ import annotations

import base64
import json
import warnings
from dataclasses import dataclass
from typing import Any

from nicegui import ui

from core.module import ParamType


def _load_microphone_options() -> dict:
    """枚举系统麦克风，返回 {None: '（系统默认）', name: name, ...} 字典供 ui.select 使用。"""
    options: dict[str | None, str] = {None: "（系统默认）"}
    try:
        import soundcard as sc
        warnings.filterwarnings("ignore", category=RuntimeWarning, module="soundcard")
        for m in sc.all_microphones(include_loopback=False):
            options[m.name] = m.name
    except Exception:
        pass  # soundcard 不可用时仅提供"系统默认"选项
    return options


_OPTIONS_LOADERS: dict[str, Any] = {
    "microphone": _load_microphone_options,
}


def _b64_encode_text(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _b64_decode_text(value: Any, fallback: str = "") -> str:
    if value in (None, ""):
        return fallback
    if not isinstance(value, str):
        return fallback
    try:
        return base64.b64decode(value.encode("ascii"), validate=True).decode("utf-8")
    except Exception:
        return value


@dataclass
class _HeaderPairsEditor:
    rows: list[dict[str, str]]

    @property
    def value(self) -> str:
        headers = {
            row.get("key", "").strip(): row.get("value", "")
            for row in self.rows
            if row.get("key", "").strip()
        }
        return _b64_encode_text(json.dumps(headers, ensure_ascii=False, indent=2))


@dataclass
class _JsonTextEditor:
    element: Any

    @property
    def value(self) -> str:
        return _b64_encode_text(self.element.value or "")


def _decode_headers_param(current_val: Any, default: Any) -> dict[str, str]:
    decoded = _b64_decode_text(current_val, _b64_decode_text(default, "{}"))
    try:
        parsed = json.loads(decoded)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k): str(v) for k, v in parsed.items()}


def _is_valid_json_object_or_array(text: str) -> bool:
    try:
        json.loads(text or "")
        return True
    except json.JSONDecodeError:
        return False


def create_module_form(
    config_attrs: list[dict],
    current_params: dict,
) -> dict[str, tuple[Any, ParamType]]:
    """
    根据 config_attrs 动态生成表单项。

    返回 {param_name: (ui_element, ParamType)} 字典，供 read_form_values() 取值。
    """
    elements: dict[str, tuple[Any, ParamType]] = {}

    for attr in config_attrs:
        name: str = attr["name"]
        param_type: ParamType = attr["type"]
        default = attr.get("default")
        required: bool = attr.get("required", False)
        description: str = attr.get("description", "")
        selectable: list | None = attr.get("selectable")
        current_val = current_params.get(name, default)

        label = f"{'* ' if required else ''}{name}"

        with ui.column().classes("w-full gap-0 q-mb-sm"):
            options_loader_key = attr.get("options_loader")
            if options_loader_key and options_loader_key in _OPTIONS_LOADERS:
                # 动态选项：调用加载器获取选项字典，渲染 ui.select 下拉菜单
                options = _OPTIONS_LOADERS[options_loader_key]()
                # 当前值不在选项 key 列表中时，fallback 到 None（系统默认）
                select_val = current_val if current_val in options else None
                el = ui.select(
                    options,
                    label=label,
                    value=select_val,
                ).classes("w-full")
            elif param_type == ParamType.Bool:
                el = ui.switch(
                    label,
                    value=bool(current_val) if current_val is not None else False,
                )
            elif param_type == ParamType.Select and selectable:
                el = ui.select(
                    selectable,
                    label=label,
                    value=current_val if current_val in selectable else selectable[0],
                ).classes("w-full")
            elif param_type == ParamType.Password:
                el = ui.input(
                    label=label,
                    value=str(current_val) if current_val is not None else "",
                    password=True,
                    password_toggle_button=True,
                ).classes("w-full")
            elif param_type == ParamType.List:
                display = (
                    json.dumps(current_val, ensure_ascii=False)
                    if current_val is not None
                    else "[]"
                )
                el = ui.input(label=f"{label} (JSON 数组)", value=display).classes("w-full")
            elif param_type == ParamType.HeaderPairsB64:
                headers = _decode_headers_param(current_val, default)
                rows = [{"key": k, "value": v} for k, v in headers.items()]
                if not rows:
                    rows.append({"key": "", "value": ""})
                el = _HeaderPairsEditor(rows)

                @ui.refreshable
                def header_editor() -> None:
                    with ui.column().classes("w-full gap-2"):
                        for idx, row in enumerate(rows):
                            with ui.row().classes("w-full items-center gap-2"):
                                ui.input(
                                    label="Header name",
                                    value=row.get("key", ""),
                                    on_change=lambda e, i=idx: rows[i].update(key=e.value or ""),
                                ).classes("col")
                                ui.input(
                                    label="Header value",
                                    value=row.get("value", ""),
                                    on_change=lambda e, i=idx: rows[i].update(value=e.value or ""),
                                ).classes("col")
                                ui.button(
                                    icon="delete",
                                    on_click=lambda i=idx: (rows.pop(i), header_editor.refresh()),
                                ).props("flat dense")
                        ui.button(
                            "添加 Header",
                            icon="add",
                            on_click=lambda: (rows.append({"key": "", "value": ""}), header_editor.refresh()),
                        ).props("outline")

                header_editor()
            elif param_type == ParamType.JsonTextB64:
                display = _b64_decode_text(current_val, _b64_decode_text(default, "{}"))
                status = ui.label("").classes("text-caption")
                el_raw = ui.textarea(label=label, value=display).classes("w-full").props("rows=14")
                el = _JsonTextEditor(el_raw)

                def _update_json_status() -> None:
                    if _is_valid_json_object_or_array(el_raw.value or ""):
                        status.text = "JSON 格式检查通过"
                        status.classes(replace="text-caption text-positive")
                    else:
                        status.text = "JSON 格式可能有误：请检查括号、引号和逗号"
                        status.classes(replace="text-caption text-negative")

                el_raw.on("update:model-value", lambda _: _update_json_status())
                _update_json_status()
            elif param_type in (ParamType.Int, ParamType.Float):
                el = ui.input(
                    label=label,
                    value=str(current_val) if current_val is not None else "",
                ).props("type=number").classes("w-full")
            else:
                # String, DirPath, FilePath, LanguageCode
                el = ui.input(
                    label=label,
                    value=str(current_val) if current_val is not None else "",
                ).classes("w-full")

            if description:
                ui.label(description).classes("text-caption text-grey-7")

        elements[name] = (el, param_type)

    return elements


def read_form_values(elements: dict[str, tuple[Any, ParamType]]) -> dict:
    """从表单元素读取当前值，转换为 Python 原生类型。"""
    result = {}
    for name, (el, param_type) in elements.items():
        try:
            val = el.value
            if param_type == ParamType.Bool:
                result[name] = bool(val)
            elif param_type == ParamType.Int:
                result[name] = int(val) if val not in (None, "") else None
            elif param_type == ParamType.Float:
                result[name] = float(val) if val not in (None, "") else None
            elif param_type == ParamType.List:
                result[name] = json.loads(val) if val else []
            elif param_type == ParamType.JsonTextB64:
                decoded = _b64_decode_text(val, "")
                if not _is_valid_json_object_or_array(decoded):
                    ui.notify(f"{name} JSON 格式可能有误，请检查括号、引号和逗号", type="warning")
                result[name] = val if val else None
            elif param_type == ParamType.HeaderPairsB64:
                result[name] = val if val else None
            else:
                result[name] = val if val else None
        except (ValueError, json.JSONDecodeError):
            result[name] = el.value
    return result
