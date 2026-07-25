from datetime import datetime, timezone

from core.packet import MessagePacket
from modules.utils.multilingual_aggregation import MultilingualPacketAggregator


def _packet(
    language: str,
    translated: str,
    group: float,
    *,
    original: str = "你好",
    pipeline_id: str = "pipe",
) -> MessagePacket:
    return MessagePacket(
        pipeline_id=pipeline_id,
        data={
            "text_original": original,
            "text_translated": translated,
            "target_lang": language,
            "timestamp_source": group,
            "is_partial": False,
        },
    )


def test_aggregates_languages_in_stable_order() -> None:
    aggregator = MultilingualPacketAggregator("timestamp_source")

    first = aggregator.add(_packet("ja", "こんにちは", 1.0))
    assert first is not None
    assert first.translated == "こんにちは"

    combined = aggregator.add(_packet("en", "hello", 1.0))
    assert combined is not None
    assert combined.translated == "hello\nこんにちは"
    assert combined.translations == {"en": "hello", "ja": "こんにちは"}
    assert combined.display_key == ("pipe", 1.0)


def test_waits_for_all_languages_seen_in_pipeline() -> None:
    aggregator = MultilingualPacketAggregator("timestamp_source")
    aggregator.add(_packet("en", "hello", 1.0))
    aggregator.add(_packet("ja", "こんにちは", 1.0))

    assert aggregator.add(_packet("en", "goodbye", 2.0)) is None
    completed = aggregator.add(_packet("ja", "さようなら", 2.0))

    assert completed is not None
    assert completed.translated == "goodbye\nさようなら"


def test_empty_group_by_uses_shared_packet_creation_time() -> None:
    aggregator = MultilingualPacketAggregator()
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    english = _packet("en", "hello", 1.0)
    japanese = _packet("ja", "こんにちは", 2.0)
    english.created_at = created_at
    japanese.created_at = created_at

    aggregator.add(english)
    combined = aggregator.add(japanese)

    assert combined is not None
    assert combined.group_value == created_at
    assert combined.translated == "hello\nこんにちは"
