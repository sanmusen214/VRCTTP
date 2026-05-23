# 业务模块详解

`modules/` 目录包含所有具体业务实现，按功能分为四个子包：

```
modules/
├── audio/       PacketProducerModule 实现（音频捕获 + VAD）
├── translation/ 语音识别（STT）+ 机器翻译（MT）
├── filter/      通用包过滤器
└── consumer/    最终消费者（终端输出 + OSC 发送）
```

---

## modules/audio/ — 音频源

### 继承关系

```
PacketProducerModule
└── VADPacketProducerModule（base.py）    含 VAD + 两种工作模式
    ├── MicrophoneSource（microphone.py） 麦克风
    └── LoopbackSource（loopback.py）     系统音频环回
```

### VADPacketProducerModule（base.py）

所有音频源的公共基类，实现 VAD 语音分段和双工作模式。

**工作模式（config `mode`）：**

#### 批处理模式（`mode="batch"`，默认）

1. 以 30ms 帧读取音频
2. 300ms 前置窗口判断：窗口内 ≥75% 有声帧 → 语音开始
3. 积累到 300ms 后置窗口 ≥75% 无声帧 → 语音结束
4. 超长截断（默认 15s）：在缓冲区找离端点最近的自然停顿拆分，前段发出，后段继续积累（不丢弃）
5. 输出一个 `is_final_segment=True, is_partial=False` 的包

#### 流式模式（`mode="streaming"`）

1. VAD 开始检测到语音
2. 语音期间每 `chunk_ms`（默认 200ms）emit 一个包：
   - `is_partial=True, is_final_segment=False`
   - 首块额外标注 `is_speech_start=True`
3. VAD 静音后，剩余音频 emit 最后一个包：
   - `is_partial=False, is_final_segment=True`

> **适合搭配 VolcStreamingSTT（streaming_mode=True）使用**，在语音段结束前即可开始识别，降低端到端延迟。

**Config 参数：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `mode` | `"batch"` | `"batch"` 或 `"streaming"` |
| `sample_rate` | `16000` | 采集采样率（Hz） |
| `vad_mode` | `2` | webrtcvad 灵敏度（0-3，3 最敏感） |
| `max_segment_seconds` | `15` | 批处理模式最大段时长（秒） |
| `chunk_ms` | `200` | 流式模式每包音频时长（ms） |

**子类须实现：**
- `_create_recorder()` → 返回 soundcard recorder context manager
- `_source_name()` → 返回可读设备名

---

### MicrophoneSource（microphone.py）

注册类型：`"microphone"`

```json
{
  "type": "microphone",
  "params": {
    "device_name": null,
    "sample_rate": 16000,
    "vad_mode": 2
  }
}
```

| 参数 | 说明 |
|------|------|
| `device_name` | 麦克风设备名，`null` 使用系统默认麦克风 |

---

### LoopbackSource（loopback.py）

注册类型：`"loopback"`

通过 WASAPI 环回捕获指定进程（或系统扬声器）的音频输出。

设备查找优先级（从高到低）：
1. 名称包含 `process_name` 的 loopback 麦克风
2. 系统默认扬声器的 loopback
3. 任意第一个 loopback 设备

```json
{
  "type": "loopback",
  "params": {
    "process_name": "VRChat.exe",
    "sample_rate": 16000,
    "vad_mode": 3,
    "mode": "streaming",
    "chunk_ms": 200
  }
}
```

| 参数 | 说明 |
|------|------|
| `process_name` | 目标进程名（如 `"VRChat.exe"`），`null` 使用默认扬声器 |

---

## modules/translation/ — 识别与翻译

### 继承关系

```
PacketConsumerModule
└── BasePacketConsumerModule（base.py）  公共配置字段
    ├── VolcStreamingSTT                  火山引擎流式 STT
    ├── LocalParaformerSTT                本地 FunASR Paraformer STT
    ├── VolcMachineTranslation            火山引擎机器翻译
    └── BaiduMachineTranslation           百度通用翻译
```

---

### BasePacketConsumerModule（base.py）

所有翻译类模块的公共基类，仅注入通用配置字段，无业务逻辑。

公共字段（`__init__` 读取后存为实例属性）：

| 属性 | Config key | 说明 |
|------|-----------|------|
| `_api_key` | `api_key` | API Key（UUID 格式） |
| `_base_url` | `base_url` | API Base URL |
| `_source_language` | `source_language` | 源语言（空字符串=自动检测） |
| `_target_language` | `target_language` | 目标语言，默认 `"zh"` |
| `_pipeline_id` | `pipeline_id` | 所属 pipeline ID（engine 注入） |

---

### VolcStreamingSTT（volc_streaming_stt.py）

注册类型：`"volc_streaming_stt"`

使用火山引擎 `bigmodel_async` WebSocket 接口做流式语音识别。

**两种工作模式（`streaming_mode`）：**

| | `streaming_mode=False`（默认） | `streaming_mode=True` |
|--|-------------------------------|----------------------|
| 输入包 | `is_final_segment=True`（完整段） | 小块 chunk（流式音频源产出） |
| 处理 | 切分为 200ms 小块推送，等待最终结果 | 边收包边推送，结果立即下发 |
| 输出 | 一个 `is_partial=False` 包 | 多个 `is_partial=True` + 最后一个 `is_partial=False` |

**鉴权方式（二选一）：**
- 新版控制台：`config["api_key"]` = UUID 格式 X-Api-Key
- 旧版控制台：`config["app_id"]` + `config["access_key"]`

**二进制协议关键点（WebSocket 帧格式）：**
- 4 字节协议头（版本 + 消息类型 + 序列化 + 压缩标志）
- 4 字节有符号序列号（正序；最后一帧取负值）
- 音频帧 gzip 压缩
- 使用 `aiohttp`（非 `websockets` 库）

**生命周期钩子实现：**
- `on_start()`：若 `streaming_mode=True`，创建 asyncio 事件循环并启动专属线程
- `on_after_stop()`：关闭 WebSocket 会话、停止 asyncio 循环

**Config 参数：**

| 参数 | 说明 |
|------|------|
| `api_key` | 火山引擎 API Key |
| `resource_id` | 资源 ID，如 `"volc.seedasr.sauc.duration"` |
| `language` | 识别语言，如 `"en"` |
| `streaming_mode` | `true` 开启流式模式，默认 `false` |

---

### VolcMachineTranslation（volc_machine_translation.py）

注册类型：`"volc_machine_translation"`

调用火山引擎 HTTP 机器翻译 API，将 `text_original` 翻译后写入 `text_translated`。

**行为：**
- `text_original` 为空时直接透传包（不翻译）
- 网络错误时记录日志并透传原始包，不抛异常
- 复用 `requests.Session`（HTTP keep-alive）

**生命周期钩子：**
- `on_after_stop()`：关闭 `requests.Session`

> **注意**：推荐通过管道中插入 `PacketFilter(final_only)` 节点在上游拦截

---

### LocalParaformerSTT（LocalSTTModel.py）

注册类型：`"local_stt"`

使用本地 FunASR `AutoModel`（默认 `paraformer-zh-streaming`）在无网络环境下做流式语音识别，无需任何 API Key。

**两种工作模式（`streaming_mode`）：**

| | `streaming_mode=False`（默认） | `streaming_mode=True` |
|--|-------------------------------|----------------------|
| 输入包 | `is_final_segment=True`（完整段） | 小块 chunk（流式音频源产出） |
| 处理 | 整段数组分窗口依次推理（`is_final=True`） | 每积累 `chunk_size[1]*960` 样本（默认 600ms）推理一次 |
| 输出 | 一个 `is_partial=False` 包 | 多个 `is_partial=True` + 最后一个 `is_partial=False` |

**音频格式转换：**
- 管道传入 16-bit PCM bytes（mono 16kHz）
- 模型需要 float32 numpy 数组，转换公式：`pcm_int16 / 32768.0`

**文字拼接行为（与云端 API 的关键差异）：**

FunASR 本地模型每次 `generate()` 仅返回当前 chunk 的**增量词语**，而非已识别文字的完整累积（云端 API 通常会返回完整句子）。因此模块内部维护 `_accumulated_text`，将每个 chunk 的识别结果追加拼接：

| 场景 | `KEY_TEXT_ORIGINAL` 内容 |
|------|--------------------------|
| partial 包（中间帧） | 本段语音迄今所有 chunk 结果的**拼接累积** |
| final 包（最终帧） | 本段语音完整拼接结果 |

示例（模型原始增量 → 包发出内容）：
```
第1帧 generate() → "你好"       → partial 包: "你好"
第2帧 generate() → "世界"       → partial 包: "你好世界"
最终帧 generate() → ""          → final   包: "你好世界"
```

`_accumulated_text` 在每段语音开始时重置（`is_speech_start=True` 或 `_reset_stream_state()`），段间互不影响。批处理模式（`_infer_full`）同理：各窗口结果拼接后一次性输出整句。

**流式模式状态管理：**
- 收到 `is_speech_start=True` 标志时自动重置 `_cache`、`_audio_buffer`、`_accumulated_text`（新语音段开始）
- partial 结果通过 `send_to_downstream()` 直接发出（携带累积全文）
- final 结果通过 `process_packet()` 返回列表由框架发出（携带完整全文）

**生命周期钩子实现：**
- `on_start()`：调用 `funasr.AutoModel(model=model_name, model_path=model_path)` 加载本地模型；`funasr` 为懒加载，不影响未使用此模块的 pipeline
- `on_after_stop()`：清空 `_cache`、`_audio_buffer`、`_segment_source_packet`、`_accumulated_text`

**Config 参数：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `model_path` | （必填） | 本地模型目录绝对路径 |
| `model_name` | `"paraformer-zh-streaming"` | 传给 AutoModel 的 model 参数 |
| `streaming_mode` | `false` | `true` 开启流式推理模式 |
| `chunk_size` | `[0, 10, 5]` | FunASR chunk_size，决定单次推理窗口（`chunk_size[1]*960` 样本） |
| `encoder_chunk_look_back` | `4` | Encoder 自注意力回看 chunk 数 |
| `decoder_chunk_look_back` | `1` | Decoder 交叉注意力回看 chunk 数 |

> **注意：** 使用前需安装 `funasr`：`pip install funasr`。批处理模式（`streaming_mode=false`）可搭配音频源 `mode="batch"`；流式模式必须搭配 `mode="streaming"`。

---

### BaiduMachineTranslation（baidu_machine_translation.py）

注册类型：`"baidu_machine_translation"`

调用百度翻译开放平台 HTTP API，将 `text_original` 翻译后写入 `text_translated`。

**行为：**
- `text_original` 为空时直接透传包（不翻译）
- `is_partial=True` 的包直接透传，不发起 API 请求（减少无效调用）
- 网络错误时记录日志并透传原始包，不抛异常
- 复用 `requests.Session`（HTTP keep-alive）
- 签名算法：`MD5(app_id + query + salt + app_key)`，salt 每次随机生成

**生命周期钩子：**
- `on_after_stop()`：关闭 `requests.Session`

> **注意**：推荐在上游插入 `PacketFilter(final_only)` 节点，确保只有完整识别结果进入翻译。

**Config 参数：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `app_id` | `""` | 百度翻译开放平台 APP ID |
| `app_key` | `""` | 百度翻译开放平台 APP Key（签名用） |
| `source_language` | `"auto"` | 源语言（`"auto"` = 自动检测） |
| `target_language` | `"zh"` | 目标语言 |

**常用语言代码：**

| 语言 | 代码 |
|------|------|
| 自动检测 | `auto` |
| 中文简体 | `zh` |
| 英语 | `en` |
| 日语 | `jp` |
| 韩语 | `kor` |
| 法语 | `fra` |
| 德语 | `de` |

**Config 示例：**

```json
"mt_zh_baidu": {
  "type": "baidu_machine_translation",
  "params": {
    "app_id": "${BAIDU_APP_ID}",
    "app_key": "${BAIDU_APP_KEY}",
    "source_language": "auto",
    "target_language": "zh"
  }
}
```

---

## modules/filter/ — 通用过滤器

### PacketFilter（packet_filter.py）

注册类型：`"filter"`

通过 `pre_process()` 钩子在 `process_packet()` 调用前做字段值检查，将过滤关注点从业务模块中抽离，以显式管道节点表达。

```
pre_process(packet):
    value = packet.is_partial  (若 field="is_partial")
               或 packet.get(field)
    match = (value == pass_when)
    if invert: match = not match
    return packet if match else None   ← None 则丢弃，不再调用 process_packet
```

**Config 参数：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `field` | `"is_partial"` | 要检查的字段名 |
| `pass_when` | `false` | 字段等于此值时放行 |
| `invert` | `false` | 是否反转判断逻辑 |

**典型用法（config.json）：**

```json
"final_only": {
  "type": "filter",
  "params": {
    "field": "is_partial",
    "pass_when": false
  }
}
```

> `is_partial` 是特殊字段，内部通过 `getattr(packet, "is_partial")` 读取 property，其他字段通过 `packet.get(field)` 读取。

---

## modules/consumer/ — 最终消费者

### TerminalConsumer（terminal.py）

注册类型：`"terminal"`

将翻译结果打印到标准输出，并通过全局回调列表通知 GUI。

**显示行为：**
- 支持 colorama 彩色输出（partial=黄色，final=绿色）

**GUI 集成：**

```python
from modules.consumer.terminal import register_gui_callback

def my_callback(pipeline_name: str, original: str, translated: str): ...
register_gui_callback(my_callback)
```

**Config 参数：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `color` | `true` | 是否彩色输出（需 colorama） |
| `format` | `"[{pipeline_name}] {text_original} → {text_translated}"` | 输出格式字符串 |
| `pipeline_name` | `""` | engine 注入的管道名称 |
| `group_by` | `""` | 分组 key（多语言合并场景） |

**format 可用占位符：**
`{pipeline_name}`, `{pipeline_id}`, `{text_original}`, `{text_translated}`, `{source_lang}`, `{target_lang}`

---

### VRChatOSCConsumer（osc_vrchat.py）

注册类型：`"osc_vrchat"`

通过 OSC 协议将翻译结果发送到 VRChat 聊天框（`/chatbox/input`）。

**VRChat 聊天框规格：**
- 最大 144 字符（超出自动截断）
- 换行使用 `\n`（CRLF 会产生空行，内部规范化处理）
- OSC 参数：`(text: str, send_immediately: bool, trigger_sfx: bool)`

**group_by 双语合并：**
配置 `group_by="timestamp_volc_stt"` 后，`mt_zh` 和 `mt_ja` 两路翻译结果会被收集到同一时间窗口，子类将所有语言翻译用换行拼接后一次性发送。

**OSC 客户端懒初始化 + 错误重连：**
发送失败时将 `_client` 置为 `None`，下次调用时重新创建（自动重连）。

**Config 参数：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `host` | `"127.0.0.1"` | OSC 目标地址 |
| `port` | `9000` | OSC 目标端口 |
| `trigger_sfx` | `false` | 是否触发 VRChat 通知音效 |
| `template` | `"{translated}"` | 文字模板，可用 `{original}` 和 `{translated}` |
| `max_chars` | `144` | 最大字符数 |
| `group_by` | `""` | 分组 key（多语言合并场景） |
