# 注意事项与开发约定

本文记录开发新模块、修改配置和运行项目时最容易踩到的点。

## 模块开发

### 选择正确基类

| 场景 | 基类 |
|------|------|
| 主动产生数据 | `PacketProducerModule` |
| 从队列取包处理 | `PacketConsumerModule` |

不要覆盖 `start()`、`stop()` 或 `_run()`，它们由框架管理。使用生命周期钩子：

```python
def on_start(self): ...
def on_before_stop(self): ...
def on_after_stop(self): ...
```

### process_packet 返回值

`process_packet()` 必须返回 `list[MessagePacket]`：

```python
def process_packet(self, packet):
    return []        # 消费后不继续发送
    return [packet]  # 透传
    return [out]     # 发送修改后的包
```

不要返回 `None`。

### 修改包前先 clone

如果模块要写入字段，应先 clone：

```python
out = packet.clone()
out.set(KEY_TEXT_TRANSLATED, translated)
return [out]
```

不要直接修改输入包。输入包可能已经被 fan-out 到其他分支。

### 不要重复发送

普通 consumer 不要在 `process_packet()` 内直接调用 `send_to_downstream()`。框架会自动发送返回列表中的每个包。

例外：某些流式模块在异步回调中主动发包时，应确保 `process_packet()` 返回 `[]`，避免重复发送。

### 字段名使用常量

使用 `core.packet` 中的 `KEY_*` 常量：

```python
packet.get(KEY_TEXT_ORIGINAL)
packet.set(KEY_TEXT_TRANSLATED, result)
```

## 配置约定

### 敏感信息

API Key 不要直接写入仓库配置，推荐使用环境变量：

```json
"api_key": "${VOLC_API_KEY}"
```

LLM 模块中的 `headers_b64` / `payload_b64` 解码后也支持 `${llm_api_key}`。

### 隐式字段

不要在配置中手动写这些字段：

- `_ref_id`
- `_display_name`
- `pipeline_id`
- `pipeline_name`
- `_queue_size`

它们由 `PipelineEngine` 注入。

### ref_id 不要随意改

`ref_id` 是 `modules` 对象的 key，也是 pipeline 路由使用的 ID。改它会破坏 routes。需要改名时修改 `display_name`。

### entry 必须是 producer

`graph.entry` 必须指向 `microphone`、`loopback` 或 `text_input` 等 producer。指向 consumer 会导致 pipeline 构建失败。

## 运行时注意事项

### 队列大小

`pipeline_queue_size` 默认较小，优先保证实时性。如果下游处理太慢，队列满时框架会清空旧包再塞入新包，避免延迟堆积。

### partial 包

流式 STT 会产生 `is_partial=true` 的中间结果。机器翻译和 LLM 翻译通常应只处理最终结果，因此建议在翻译前插入：

```json
{
  "type": "filter",
  "params": {
    "field": "is_partial",
    "pass_when": false
  }
}
```

### 批处理与流式模式要匹配

音频源 `mode="streaming"` 应搭配 STT `streaming_mode=true`。

音频源 `mode="batch"` 更适合搭配非流式识别。

### VRChat OSC

使用 `osc_vrchat` 输出前：

- 在 VRChat 中启用 OSC。
- 默认发送到 `127.0.0.1:9000`。
- Chatbox 通常限制 144 字符，模块会按 `max_chars` 截断。

使用 `sync_vrc_mic=true` 前：

- VRChat 需要启用 OSC 输出。
- 本程序监听 `127.0.0.1:9001`。
- 端口不能被其他程序占用。
- 未收到状态前按麦克风关闭处理。

### 平台限制

项目主要面向 Windows。`LoopbackSource` 依赖 WASAPI loopback，macOS/Linux 需要额外音频路由方案。

## LLM 模块注意事项

`llm_openai_api_call` 是通用 HTTP JSON 调用器，不绑定特定厂商。

使用时注意：

- `target_language` 是给下游消费者看的标记，需要用户自行填写。
- `headers_b64` 必须解码为 JSON object。
- `payload_b64` 必须解码为 JSON object 文本。
- `%{original}` 只在 payload 文本中替换。
- `${llm_api_key}` 从环境变量读取。
- GUI 中编辑的是明文，保存后自动 base64 编码。

如果响应结构不是模块默认兼容的格式，需要调整 `_extract_text()`。

## 新增模块 checklist

1. 选择正确基类。
2. 实现 `require_attributes_in_packages()`。
3. 实现 `add_attributes_in_packages()`。
4. 实现 `get_config_attributes()`。
5. 实现 `process_packet()` 或 `produce_packets()`。
6. 需要外部连接时在生命周期钩子中创建和关闭资源。
7. 在 `core/engine.py` 的注册表中注册 type。
8. 更新 `ai_document/modules.md` 和 `ai_document/config.md`。
9. 为高风险逻辑补测试或 smoke test。

## 调试建议

- 先用 `text_input -> 翻译模块 -> terminal` 测翻译模块。
- 再接入 STT。
- 最后接入音频源和 VRChat OSC。
- 网络 API 失败时优先检查环境变量、endpoint、header 和 payload。
- GUI 保存配置后记得重载。
