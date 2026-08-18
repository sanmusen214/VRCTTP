# 流式音频可靠性修复

## 问题

麦克风流式模式实际约每 180ms 产生一个 PCM 包，本地 Paraformer 每累积
600ms 同步执行一次推理。原有通用队列默认只容纳 2 个包，满时清空
所有旧包。当单次推理赶不上采集时，中间 PCM、final 或下一段 start 都
可能被丢弃，造成缺字、漏词或 cache 跨段。

背景噪声被 VAD 持续判为语音时，即使模型一直返回空文本，也会继续产生
短音频包，放大上述队列拥塞。

## 修复

1. 在 `core/runtime_policies.py` 声明运行策略：仅对 `local_stt` 且
   `streaming_mode=true` 注入 `coalesce_streaming_audio`。
2. `core/packet_queue.py` 实现动态 PCM 队列。达到软阈值时，同一 pipeline、
   同一语音段的相邻包按顺序合并；final/start 边界不合并，必要时动态扩容。
3. 合并包记录 `audio_chunk_idx` 到 `audio_chunk_end_idx` 的序号范围。本地 STT
   发现断号时告警并重置该 pipeline 的流式 cache。
4. 合并 final 可能携带多个模型窗口。处理时先以标准 600ms 窗口逐块推理，
   仅最后一块使用 `is_final=true`。
5. 队列合并积压超过 3 秒后按倍增阈值告警。PortAudio 输入溢出也按
   1、2、4、8... 次节流告警，不再静默忽略真实录音缺损。

## 边界

该策略保证 Pipeline 拥塞时不再主动丢弃流式本地 STT 音频，并将大量等待
的小包压缩成少量动态 PCM 缓冲。它不能改变模型的计算速度；如果推理长期
慢于实时音频，为保证无损，延迟仍会增长。积压告警用于区分这种算力瓶颈和
普通的识别准确率问题。

WebRTC `vad_mode` 表示激进程度，3 对非语音过滤最严格，不是“最灵敏”。
背景噪声或轻声语音环境需根据实际输入在 0-3 之间测试。

## 验证

`tests/test_streaming_audio_queue.py` 覆盖：

- 队列拥塞后 PCM 字节完整且顺序不变。
- final 可合并，下一语音段 start 必须保持独立。
- 运行策略只匹配流式本地 STT。
- 长 final 按标准窗口切分，仅末窗口标记 final。
