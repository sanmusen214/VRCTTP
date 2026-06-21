"""Module identity helpers shared by configuration and GUI code."""

from __future__ import annotations

import hashlib


def module_ref_id(display_name: str) -> str:
    """Return the stable internal ref_id derived from an initial display name."""
    normalized = display_name.strip()
    if not normalized:
        raise ValueError("display_name cannot be empty")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"mod_{digest}"


def module_display_name(ref_id: str, module_config: dict) -> str:
    """Read display_name while keeping legacy configurations usable."""
    return str(module_config.get("display_name") or ref_id)


def ensure_module_display_names(config: dict) -> dict:
    """Add missing display names without changing legacy ref_ids or routes."""
    modules = config.get("modules", {})
    if not isinstance(modules, dict):
        return config
    for ref_id, module_config in modules.items():
        if ref_id.startswith("_") or not isinstance(module_config, dict):
            continue
        module_config.setdefault("display_name", ref_id)
    return config
