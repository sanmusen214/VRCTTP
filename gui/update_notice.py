"""将更新检查状态转换为首页版本入口的展示模型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class UpdateNotice:
    title: str
    version_text: str
    release_notes: str
    badge_text: str
    has_new_version: bool


def build_update_notice(
    info: Any,
    *,
    current_version: str,
    local_release_notes: str,
) -> UpdateNotice:
    """无论更新检查是否完成，都生成可供用户查看的版本说明。"""
    fallback_notes = local_release_notes.strip() or "暂无版本更新说明。"
    if info is not None and bool(getattr(info, "has_new_version", False)):
        latest = str(getattr(info, "version_str", "") or "未知")
        return UpdateNotice(
            title="发现新版本",
            version_text=f"最新版本：{latest}（当前版本：{current_version}）",
            release_notes=str(
                getattr(info, "update_body_text", "") or fallback_notes
            ),
            badge_text=f"新版本 {latest}",
            has_new_version=True,
        )

    online_version = (
        str(getattr(info, "version_str", "") or "") if info is not None else ""
    )
    version_text = f"当前版本：{current_version}"
    if online_version:
        version_text += f"（线上最新版本：{online_version}）"
    return UpdateNotice(
        title="版本更新说明",
        version_text=version_text,
        release_notes=str(
            getattr(info, "update_body_text", "") or fallback_notes
        ),
        badge_text="版本说明",
        has_new_version=False,
    )
