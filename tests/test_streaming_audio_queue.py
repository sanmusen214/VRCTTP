from __future__ import annotations

from core.packet import (
    KEY_AUDIO_CHUNK_END_INDEX,
    KEY_AUDIO_CHUNK_INDEX,
    KEY_AUDIO_DATA,
    KEY_IS_FINAL_SEGMENT,
    KEY_IS_PARTIAL,
    KEY_IS_SPEECH_START,
    KEY_SAMPLE_RATE,
    MessagePacket,
)
from core.packet_queue import CoalescingStreamingAudioQueue
from core.runtime_policies import apply_module_runtime_policies
from modules.translation.LocalSTTModel import LocalParaformerSTT


def _audio_packet(
    payload: bytes,
    *,
    chunk_idx: int | None,
    speech_start: bool = False,
    final: bool = False,
    pipeline_id: str = "pipeline",
) -> MessagePacket:
    packet = MessagePacket(pipeline_id=pipeline_id)
    packet.set(KEY_AUDIO_DATA, payload)
    packet.set(KEY_SAMPLE_RATE, 16000)
    packet.set(KEY_IS_SPEECH_START, speech_start)
    packet.set(KEY_IS_FINAL_SEGMENT, final)
    packet.set(KEY_IS_PARTIAL, not final)
    packet.is_partial = not final
    if chunk_idx is not None:
        packet.set(KEY_AUDIO_CHUNK_INDEX, chunk_idx)
    return packet


def test_congested_streaming_audio_is_coalesced_without_byte_loss() -> None:
    audio_queue = CoalescingStreamingAudioQueue(maxsize=2, warning_seconds=0)
    audio_queue.put_nowait(_audio_packet(b"a", chunk_idx=0, speech_start=True))
    audio_queue.put_nowait(_audio_packet(b"b", chunk_idx=1))
    audio_queue.put_nowait(_audio_packet(b"c", chunk_idx=2))

    first = audio_queue.get_nowait()
    merged = audio_queue.get_nowait()

    assert first.get(KEY_AUDIO_DATA) == b"a"
    assert merged.get(KEY_AUDIO_DATA) == b"bc"
    assert merged.get(KEY_AUDIO_CHUNK_INDEX) == 1
    assert merged.get(KEY_AUDIO_CHUNK_END_INDEX) == 2


def test_long_backlog_preserves_every_chunk_in_order() -> None:
    audio_queue = CoalescingStreamingAudioQueue(maxsize=2, warning_seconds=0)
    expected = bytearray()
    for chunk_idx in range(100):
        payload = chunk_idx.to_bytes(2, "little")
        expected.extend(payload)
        audio_queue.put_nowait(
            _audio_packet(payload, chunk_idx=chunk_idx, speech_start=chunk_idx == 0)
        )

    actual = bytearray()
    while not audio_queue.empty():
        actual.extend(audio_queue.get_nowait().get(KEY_AUDIO_DATA))

    assert actual == expected


def test_final_packet_is_coalesced_but_next_segment_boundary_is_preserved() -> None:
    audio_queue = CoalescingStreamingAudioQueue(maxsize=1, warning_seconds=0)
    audio_queue.put_nowait(_audio_packet(b"a", chunk_idx=0, speech_start=True))
    audio_queue.put_nowait(_audio_packet(b"b", chunk_idx=1))
    audio_queue.put_nowait(_audio_packet(b"z", chunk_idx=None, final=True))
    audio_queue.put_nowait(_audio_packet(b"n", chunk_idx=0, speech_start=True))

    completed = audio_queue.get_nowait()
    next_segment = audio_queue.get_nowait()

    assert completed.get(KEY_AUDIO_DATA) == b"abz"
    assert completed.get(KEY_IS_FINAL_SEGMENT) is True
    assert completed.is_partial is False
    assert next_segment.get(KEY_AUDIO_DATA) == b"n"
    assert next_segment.get(KEY_IS_SPEECH_START) is True


def test_runtime_queue_policy_only_matches_streaming_local_stt() -> None:
    streaming_params = {"streaming_mode": True}
    batch_params = {"streaming_mode": False}
    other_params = {"streaming_mode": True}

    apply_module_runtime_policies("local_stt", streaming_params)
    apply_module_runtime_policies("local_stt", batch_params)
    apply_module_runtime_policies("volc_streaming_stt", other_params)

    assert streaming_params["_queue_policy"] == "coalesce_streaming_audio"
    assert "_queue_policy" not in batch_params
    assert "_queue_policy" not in other_params


def test_coalesced_final_audio_is_inferred_in_standard_windows() -> None:
    calls: list[tuple[int, bool]] = []

    class _FakeModel:
        def generate(self, **kwargs):
            calls.append((len(kwargs["input"]), kwargs["is_final"]))
            return [{"text": "x"}]

    stt = LocalParaformerSTT(
        "local",
        {
            "model_path": "unused",
            "streaming_mode": True,
            "chunk_size": [0, 10, 5],
        },
    )
    stt._model = _FakeModel()
    sample_count = stt._chunk_stride + 2400
    packet = _audio_packet(
        b"\x00\x00" * sample_count,
        chunk_idx=0,
        speech_start=True,
        final=True,
    )

    result = stt.process_packet(packet)

    assert calls == [(stt._chunk_stride, False), (2400, True)]
    assert result[0].get("text_original") == "xx"
