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

import json
import warnings
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
            else:
                result[name] = val if val else None
        except (ValueError, json.JSONDecodeError):
            result[name] = el.value
    return result
