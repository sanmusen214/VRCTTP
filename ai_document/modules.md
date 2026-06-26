# 业务模块目录

本文说明 `modules/` 下各业务模块的职责、输入输出字段和配置参数。模块元信息由三个类方法描述：`require_attributes_in_packages()`、`add_attributes_in_packages()` 和 `get_config_attributes()`。

## 模块总表

| type | 类 | 类别 | 说明 |
|------|----|------|------|
| `microphone` | `MicrophoneSource` | 音频源 | 采集麦克风音频 |
| `loopback` | `LoopbackSource` | 音频源 | 捕获系统或指定进程音频 |
| `text_input` | `TextInput` | 文本源/中间节点 | GUI 手动文字输入，也可透传上游包 |
| `volc_streaming_stt` | `VolcStreamingSTT` | STT | 火山引擎流式语音识别 |
| `local_stt` | `LocalParaformerSTT` | STT | 本地 FunASR 语音识别 |
| `volc_machine_translation` | `VolcMachineTranslation` | 翻译 | 火山引擎机器翻译 |
| `baidu_machine_translation` | `BaiduMachineTranslation` | 翻译 | 百度通用翻译 |
| `llm_openai_api_call` | `LLMOpenAIAPICall` | 翻译 | 自定义 LLM HTTP JSON 翻译 |
| `filter` | `PacketFilter` | 过滤 | 通用字段过滤器 |
| `terminal` | `TerminalConsumer` | 输出 | 终端和 GUI 输出缓冲 |
| `osc_vrchat` | `VRChatOSCConsumer` | 输出 | VRChat chatbox OSC 输出 |

## 音频源

### MicrophoneSource

注册类型：`microphone`

采集系统麦克风音频，并通过 VAD 生成语音段包。

主要配置：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `device_name` | `None` | 麦克风设备名，空值表示系统默认 |
| `sample_rate` | `16000` | 目标采样率 |
| `vad_mode` | `2` | VAD 灵敏度，0-3 |
| `mode` | `batch` | `batch` 或 `streaming` |
| `max_segment_seconds` | `15` | 批处理模式最大语音段长度 |
| `chunk_ms` | `200` | 流式模式每包音频时长 |
| `sync_vrc_mic` | `false` | 是否跟随 VRChat 游戏内麦克风状态 |

输出字段包括 `audio_data`、`sample_rate`、`source_type`、`source_name`、`is_final_segment`、`is_partial`、`is_speech_start`、`audio_chunk_idx` 和 `timestamp`。

### LoopbackSource

注册类型：`loopback`

通过 WASAPI loopback 捕获系统输出或指定进程音频。Windows 是主要支持平台。

主要配置：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `process_name` | `VRChat.exe` | 目标进程名；空值表示默认扬声器 |
| `sample_rate` | `16000` | 目标采样率 |
| `vad_mode` | `2` | VAD 灵敏度 |
| `mode` | `batch` | `batch` 或 `streaming` |
| `max_segment_seconds` | `15` | 批处理模式最大语音段长度 |
| `chunk_ms` | `200` | 流式模式每包音频时长 |
| `sync_vrc_mic` | `false` | 是否跟随 VRChat 游戏内麦克风状态 |

设备选择优先级：

1. 名称包含 `process_name` 的 loopback 设备。
2. 系统默认扬声器的 loopback 设备。
3. 任意第一个 loopback 设备。

### VRChat 麦克风同步

`sync_vrc_mic=true` 时，音频源会监听 `127.0.0.1:9001/UDP` 的 `/avatar/parameters/MuteSelf`：

- `true`：游戏内麦克风关闭，拦截音频包。
- `false`：游戏内麦克风开启，放行音频包。
- 尚未收到状态：按关闭处理。

需要先在 VRChat 中启用 OSC。监听器是进程级共享实例，多个音频模块不会重复占用端口。

## 文本输入

### TextInput

注册类型：`text_input`

`TextInput` 既可作为 pipeline 入口，也可放在中间透传上游包。作为入口时，它接收 GUI `/output` 页面提交的文本，并创建带 `text_original` 的标准包。

配置：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `source_lang` | `auto` | GUI 手动输入文本的来源语言标记 |

输出字段：

| 字段 | 说明 |
|------|------|
| `text_original` | 用户输入文本 |
| `is_final_segment` | 固定为 `True` |
| `is_partial` | 固定为 `False` |
| `source_lang` | 来自配置 |

## 语音识别

### VolcStreamingSTT

注册类型：`volc_streaming_stt`

使用火山引擎 WebSocket API 做语音识别。支持批处理和流式两种模式。

主要配置：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `api_key` | `""` | 新版控制台 `X-Api-Key` |
| `app_id` | `""` | 旧版控制台 App ID |
| `access_key` | `""` | 旧版控制台 Access Key |
| `resource_id` | `volc.seedasr.sauc.duration` | 资源 ID |
| `language` | `""` | 识别语言，空值表示自动 |
| `chunk_ms` | `200` | 音频分块时长 |
| `streaming_mode` | `True` | 是否启用流式会话 |

输入字段：

| 字段 | 说明 |
|------|------|
| `audio_data` | PCM 音频 bytes |
| `is_final_segment` | 是否最终音频包 |
| `is_partial` | 是否流式中间包 |
| `is_speech_start` | 是否新语音段首包 |

输出字段：

| 字段 | 说明 |
|------|------|
| `text_original` | 识别文本 |
| `is_partial` | 中间结果或最终结果 |
| `is_final_segment` | 最终语音段标记 |

### LocalParaformerSTT

注册类型：`local_stt`

使用本地 FunASR 模型做语音识别。适合无网络场景，但依赖模型文件和相关 Python 包。

主要配置：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `model_path` | 必填 | 本地模型目录 |
| `model_name` | `paraformer-zh-streaming` | 传给 FunASR 的模型名 |
| `streaming_mode` | `false` | 是否使用流式模型 |
| `chunk_size` | `[0, 10, 5]` | 流式推理窗口 |
| `encoder_chunk_look_back` | `4` | Encoder 回看 chunk 数 |
| `decoder_chunk_look_back` | `1` | Decoder 回看 chunk 数 |

流式模式下，FunASR 每次返回增量文本，模块内部会累积成完整 `text_original`。

## 翻译模块

所有翻译模块通常读取 `text_original`，写入 `text_translated` 和 `target_lang`。建议在翻译前接入 `filter`，只放行 `is_partial=false` 的最终识别包。

### VolcMachineTranslation

注册类型：`volc_machine_translation`

调用火山引擎机器翻译 HTTP API。

主要配置：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `api_key` | `""` | 新版控制台 API Key |
| `app_id` | `""` | 旧版 App ID |
| `access_key` | `""` | 旧版 Access Key |
| `source_language` | `""` | 源语言，空值表示自动 |
| `target_language` | `zh` | 目标语言 |

### BaiduMachineTranslation

注册类型：`baidu_machine_translation`

调用百度翻译开放平台 HTTP API。签名为 `MD5(app_id + query + salt + app_key)`。

主要配置：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `app_id` | `""` | 百度翻译 APP ID |
| `app_key` | `""` | 百度翻译密钥 |
| `source_language` | `auto` | 源语言 |
| `target_language` | `zh` | 目标语言 |

常用语言代码：`auto`、`zh`、`en`、`jp`、`kor`、`fra`、`de`、`spa`。

### LLMOpenAIAPICall

注册类型：`llm_openai_api_call`

通用 LLM HTTP JSON 翻译模块。它把 `text_original` 通过 `%{original}` 占位符嵌入自定义 payload，POST 到配置的 LLM API，再从响应中提取文本写入 `text_translated`。

主要配置：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `target_language` | `please_fill_target_language` | 目标语言标记，建议使用下划线 |
| `api_url` | `https://ark.cn-beijing.volces.com/api/v3/responses` | LLM API endpoint |
| `headers_b64` | base64(JSON object) | HTTP headers，GUI 中明文编辑 |
| `payload_b64` | base64(JSON text) | 请求 JSON payload，GUI 中明文编辑 |

占位符：

| 占位符 | 位置 | 说明 |
|--------|------|------|
| `${llm_api_key}` | headers 或 payload | 从环境变量 `llm_api_key` 读取 |
| `%{original}` | payload | 替换为上游 `text_original`，替换时会做 JSON 字符串转义 |

默认 header 解码后：

```json
{
  "Authorization": "Bearer ${llm_api_key}",
  "Content-Type": "application/json"
}
```

响应文本提取兼容：

- `output_text`
- `choices[].message.content`
- `output[].content[].text`
- `text`
- `translation`
- `translated_text`
- `result`

## 过滤模块

### PacketFilter

注册类型：`filter`

根据包字段值决定是否放行。常用于丢弃流式中间识别结果，只让最终结果进入翻译。

配置：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `field` | `is_partial` | 要检查的字段 |
| `pass_when` | `false` | 字段等于此值时放行 |
| `invert` | `false` | 是否反转判断 |

典型配置：

```json
{
  "type": "filter",
  "params": {
    "field": "is_partial",
    "pass_when": false
  }
}
```

## 输出模块

### TerminalConsumer

注册类型：`terminal`

将结果打印到终端，并通过 GUI callback 写入 `/output` 页面缓冲区。

配置：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `color` | `true` | 是否彩色输出 |
| `format` | `[{pipeline_name}] {text_original} → {text_translated}` | 输出模板 |
| `group_by` | `""` | 合并多路翻译结果的分组 key |

模板可用字段：`pipeline_name`、`pipeline_id`、`text_original`、`text_translated`、`source_lang`、`target_lang`。

### VRChatOSCConsumer

注册类型：`osc_vrchat`

通过 OSC `/chatbox/input` 将文本发送到 VRChat 聊天框。

配置：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `host` | `127.0.0.1` | OSC 目标地址 |
| `port` | `9000` | OSC 目标端口 |
| `trigger_sfx` | `false` | 是否触发通知音效 |
| `template` | `{translated}` | 输出文本模板 |
| `max_chars` | `144` | VRChat 聊天框最大字符数 |
| `group_by` | `""` | 合并多路翻译结果的分组 key |

`template` 可使用 `{original}` 和 `{translated}`。模块会规范化换行并截断超过 `max_chars` 的文本。
