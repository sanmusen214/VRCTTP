from core.engine import PipelineEngine
from core.module import PacketProducerModule
from core.pipeline import Pipeline
from gui.pages.home import _status_detail


class _Producer(PacketProducerModule):
    def produce_packets(self):
        yield from ()


def test_status_supports_pipeline_without_consumer() -> None:
    producer = _Producer("pipeline.audio", {})
    pipeline = Pipeline(
        pipeline_id="11",
        name="producer only",
        all_modules={"audio": producer},
        entry="audio",
        routes={},
    )
    engine = PipelineEngine()
    engine._pipelines["11"] = pipeline

    assert engine.get_status() == [
        {
            "id": "11",
            "name": "producer only",
            "status": "stopped",
            "audio_source_type": "_Producer",
            "translation_types": [],
            "translation_type": None,
            "consumer_types": [],
        }
    ]


def test_gui_status_detail_handles_empty_and_legacy_statuses() -> None:
    assert _status_detail({"audio_source_type": "Audio", "translation_types": []}) == (
        "Audio",
        "无",
        "无",
    )
    assert _status_detail({"translation_type": "LegacyConsumer"}) == (
        "未知",
        "LegacyConsumer",
        "无",
    )
