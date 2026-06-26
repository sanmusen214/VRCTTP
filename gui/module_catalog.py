"""Shared module catalog helpers for GUI ordering and grouping."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Iterable

from core.module_identity import module_display_name


MODULE_CATEGORY_ORDER: tuple[tuple[str, str], ...] = (
    ("input", "输入源"),
    ("stt", "语音识别"),
    ("filter", "过滤处理"),
    ("translation", "翻译"),
    ("output", "输出"),
    ("other", "其他"),
)

_TYPE_CATEGORY: dict[str, str] = {
    "microphone": "input",
    "loopback": "input",
    "text_input": "input",
    "volc_streaming_stt": "stt",
    "local_stt": "stt",
    "filter": "filter",
    "volc_machine_translation": "translation",
    "baidu_machine_translation": "translation",
    "llm_openai_api_call": "translation",
    "terminal": "output",
    "osc_vrchat": "output",
}

_CATEGORY_LABELS = dict(MODULE_CATEGORY_ORDER)
_CATEGORY_INDEX = {key: index for index, (key, _) in enumerate(MODULE_CATEGORY_ORDER)}


def module_category_for_type(type_name: str) -> str:
    """Return the pipeline-oriented category key for a registered module type."""
    if type_name in _TYPE_CATEGORY:
        return _TYPE_CATEGORY[type_name]
    return "other"


def module_category_label(category: str) -> str:
    """Return a human-readable category label."""
    return _CATEGORY_LABELS.get(category, _CATEGORY_LABELS["other"])


def module_type_sort_key(type_name: str) -> tuple[int, str]:
    """Sort module types by pipeline flow category, then by type name."""
    category = module_category_for_type(type_name)
    return (_CATEGORY_INDEX.get(category, _CATEGORY_INDEX["other"]), type_name)


def group_module_types(type_names: Iterable[str]) -> OrderedDict[str, list[str]]:
    """Group module type names by pipeline flow category."""
    grouped: OrderedDict[str, list[str]] = OrderedDict(
        (category, []) for category, _ in MODULE_CATEGORY_ORDER
    )
    for type_name in sorted(type_names, key=module_type_sort_key):
        grouped.setdefault(module_category_for_type(type_name), []).append(type_name)
    return OrderedDict((category, values) for category, values in grouped.items() if values)


def group_module_instances(
    modules_cfg: dict[str, Any],
    ref_ids: Iterable[str] | None = None,
) -> OrderedDict[str, list[tuple[str, dict]]]:
    """Group configured module instances by the category of their registered type."""
    ids = list(ref_ids) if ref_ids is not None else list(modules_cfg.keys())
    grouped: OrderedDict[str, list[tuple[str, dict]]] = OrderedDict(
        (category, []) for category, _ in MODULE_CATEGORY_ORDER
    )
    for ref_id in ids:
        if ref_id.startswith("_"):
            continue
        mod_def = modules_cfg.get(ref_id)
        if not isinstance(mod_def, dict):
            continue
        category = module_category_for_type(str(mod_def.get("type", "")))
        grouped.setdefault(category, []).append((ref_id, mod_def))

    for values in grouped.values():
        values.sort(key=lambda item: module_display_name(item[0], item[1]).lower())
    return OrderedDict((category, values) for category, values in grouped.items() if values)


def grouped_type_select_options(type_names: Iterable[str]) -> dict[str, str]:
    """Build NiceGUI select options with category labels embedded in display text."""
    options: dict[str, str] = {}
    for category, values in group_module_types(type_names).items():
        category_label = module_category_label(category)
        for type_name in values:
            options[type_name] = f"{category_label} / {type_name}"
    return options


def grouped_module_select_options(
    modules_cfg: dict[str, Any],
    ref_ids: Iterable[str] | None = None,
) -> dict[str, str]:
    """Build grouped module instance options whose values are ref_ids."""
    options: dict[str, str] = {}
    for category, items in group_module_instances(modules_cfg, ref_ids).items():
        category_label = module_category_label(category)
        for ref_id, mod_def in items:
            label = module_display_name(ref_id, mod_def)
            type_name = mod_def.get("type", "?")
            options[ref_id] = f"{category_label} / {label}  [{type_name}]"
    return options
