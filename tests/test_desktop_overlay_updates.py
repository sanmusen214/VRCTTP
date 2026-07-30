from modules.consumer.desktop_overlay import (
    MAX_OVERLAY_HISTORY,
    MAX_PENDING_GROUPS,
    MAX_UPDATES_PER_TICK,
    DesktopOverlayService,
    _OverlayUpdate,
    _config_from_dict,
)


def _new_service() -> DesktopOverlayService:
    previous = DesktopOverlayService._instance
    DesktopOverlayService._instance = None
    try:
        return DesktopOverlayService.instance()
    finally:
        DesktopOverlayService._instance = previous


def test_history_size_is_hard_capped_at_30() -> None:
    assert MAX_OVERLAY_HISTORY == 30
    assert _config_from_dict({"history_size": 5000}).history_size == 30
    assert _config_from_dict({}).history_size == 30


def test_pending_updates_keep_only_latest_state_per_group() -> None:
    service = _new_service()
    key = ("pipeline", 1.0)
    service.submit(_OverlayUpdate(key, "old"))
    service.submit(_OverlayUpdate(key, "new"))

    assert service._take_pending_updates() == [_OverlayUpdate(key, "new")]


def test_pending_updates_are_limited_per_tick() -> None:
    service = _new_service()
    for index in range(MAX_UPDATES_PER_TICK + 7):
        service.submit(
            _OverlayUpdate(("pipeline", float(index)), f"text-{index}")
        )

    first_batch = service._take_pending_updates()
    second_batch = service._take_pending_updates()

    assert len(first_batch) == MAX_UPDATES_PER_TICK
    assert len(second_batch) == 7
    assert first_batch[0].text == "text-0"
    assert second_batch[-1].text == f"text-{MAX_UPDATES_PER_TICK + 6}"


def test_pending_groups_discard_oldest_beyond_visible_capacity() -> None:
    service = _new_service()
    for index in range(MAX_PENDING_GROUPS + 5):
        service.submit(
            _OverlayUpdate(("pipeline", float(index)), f"text-{index}")
        )

    updates = service._take_pending_updates(MAX_PENDING_GROUPS)

    assert len(updates) == MAX_PENDING_GROUPS
    assert updates[0].text == "text-5"
    assert updates[-1].text == f"text-{MAX_PENDING_GROUPS + 4}"
