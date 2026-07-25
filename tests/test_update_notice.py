from types import SimpleNamespace

from gui.update_notice import build_update_notice


def test_notice_is_available_before_update_check_finishes() -> None:
    notice = build_update_notice(
        None,
        current_version="1.2.3",
        local_release_notes="# 本地说明",
    )

    assert notice.badge_text == "版本说明"
    assert notice.version_text == "当前版本：1.2.3"
    assert notice.release_notes == "# 本地说明"
    assert notice.has_new_version is False


def test_notice_uses_online_notes_when_no_new_version() -> None:
    info = SimpleNamespace(
        has_new_version=False,
        version_str="1.2.3",
        update_body_text="线上版本说明",
    )

    notice = build_update_notice(
        info,
        current_version="1.2.3",
        local_release_notes="本地说明",
    )

    assert notice.title == "版本更新说明"
    assert notice.badge_text == "版本说明"
    assert notice.release_notes == "线上版本说明"
    assert "线上最新版本：1.2.3" in notice.version_text


def test_new_version_notice_keeps_update_call_to_action() -> None:
    info = SimpleNamespace(
        has_new_version=True,
        version_str="1.3.0",
        update_body_text="新版说明",
    )

    notice = build_update_notice(
        info,
        current_version="1.2.3",
        local_release_notes="本地说明",
    )

    assert notice.title == "发现新版本"
    assert notice.badge_text == "新版本 1.3.0"
    assert notice.release_notes == "新版说明"
    assert notice.has_new_version is True
