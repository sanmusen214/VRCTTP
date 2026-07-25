"""启动时自动补齐的软件内建默认模块。

新增一个自动补齐模块时，只需向 ``DEFAULT_MODULES`` 追加声明，无需修改补全流程。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


# 声明格式：
# {
#     "ref_id": 建议使用的配置键（冲突时自动追加 _2、_3……）,
#     "match": 判断用户配置中是否已存在该模块的字段条件,
#     "definition": 缺失时写入 config["modules"] 的完整模块定义,
# }
DEFAULT_MODULES: list[dict[str, Any]] = [
    {
        "ref_id": "桌面翻译窗口",
        "match": {"type": "desktop_overlay"},
        "definition": {
            "type": "desktop_overlay",
            "params": {
                "opacity": 0.78,
                "font_size": 20,
                "width": 720,
                "height": 360,
                "topmost": True,
                "history_size": 200,
                "group_by": "timestamp_中间件-GUI输入文字",
            },
            "display_name": "桌面翻译窗口",
        },
    },
]


def ensure_default_modules(
    config: dict,
    defaults: list[dict[str, Any]] | None = None,
) -> bool:
    """按声明列表补齐缺失模块，发生任何修改时返回 ``True``。"""
    modules = config.setdefault("modules", {})
    if not isinstance(modules, dict):
        raise ValueError("config.modules 必须是对象")

    changed = False
    for default in DEFAULT_MODULES if defaults is None else defaults:
        preferred_ref_id, match, definition = _validate_default(default)
        if any(
            isinstance(existing, dict)
            and all(existing.get(key) == value for key, value in match.items())
            for existing in modules.values()
        ):
            continue

        ref_id = preferred_ref_id
        suffix = 2
        while ref_id in modules:
            ref_id = f"{preferred_ref_id}_{suffix}"
            suffix += 1
        modules[ref_id] = deepcopy(definition)
        changed = True
    return changed


def _validate_default(
    default: dict[str, Any],
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    try:
        ref_id = str(default["ref_id"]).strip()
        match = default["match"]
        definition = default["definition"]
    except (KeyError, TypeError) as exc:
        raise ValueError(
            "默认模块声明必须包含 ref_id、match 和 definition"
        ) from exc
    if not ref_id:
        raise ValueError("默认模块声明的 ref_id 不能为空")
    if not isinstance(match, dict) or not match:
        raise ValueError(f"默认模块 {ref_id!r} 的 match 必须是非空对象")
    if not isinstance(definition, dict):
        raise ValueError(f"默认模块 {ref_id!r} 的 definition 必须是对象")
    return ref_id, match, definition
