# 业务模块详解

`modules/` 目录包含所有具体业务实现，按功能分为四个子包：

---

## 模块元信息接口（ParamType + 三个类方法）

### ParamType 枚举（`core/module.py`）

每个模块类通过三个类方法（classmethod）对外暴露自身的**数据契约**和**配置参数描述**，GUI 动态表单和文档自动生成以此为基础。`ParamType` 用于标注配置参数的数据类型：

| 枚举成员 | 值 | 含义 |
|----------|-----|------|
| `ParamType.String` | `"string"` | 普通文本输入 |
| `ParamType.Int` | `"int"` | 整数（可设置 min/max） |
| `ParamType.Float` | `"float"` | 浮点数 |
| `ParamType.Bool` | `"bool"` | 布尔开关 |
| `ParamType.Password` | `"password"` | 敏感文本（遮掩显示） |
| `ParamType.Select` | `"select"` | 下拉单选（需提供 selectable 列表） |
| `ParamType.DirPath` | `"dirpath"` | 目录路径选择器 |
| `ParamType.FilePath` | `"filepath"` | 文件路径选择器 |
| `ParamType.List` | `"list"` | JSON 列表输入 |
| `ParamType.LanguageCode` | `"language_code"` | 语言代码（如 `"zh"`, `"en"`） |

```python
from core.module import ParamType
print(ParamType.Password.value)  # → "password"
```

---

### 三个抽象类方法

所有叶子模块类都必须实现以下三个 `@classmethod`。

#### `require_attributes_in_packages() → list[dict]`

声明本模块从**上游包**（入参 packet）中读取哪些字段。

返回字段 schema（每项为 dict）：

| Key | 类型 | 说明 |
|-----|------|------|
| `name` | `str` | 字段名（对应 `packet.get(name)` 或 packet 属性名） |
| `must_have` | `bool` | `True` = 必须存在，`False` = 可选消费 |
| `description` | `str` | 字段用途描述 |

示例（`VolcStreamingSTT`）：
```python
[
  {"name": "audio_data",        "must_have": True,  "description": "PCM 音频字节数据"},
  {"name": "is_final_segment",  "must_have": True,  "description": "是否为最终语音段"},
  {"name": "is_partial",        "must_have": False, "description": "是否为流式中间帧"},
  {"name": "is_speech_start",   "must_have": False, "description": "是否为语音段首帧"},
]
```

---

#### `add_attributes_in_packages() → list[dict]`

声明本模块向**下游包**写入哪些字段（生产者写入 or 消费者添加）。

返回与 `require_attributes_in_packages()` 相同的 schema。

`PacketProducerModule` 子类（音频源）在此声明输出字段；`PacketConsumerModule` 子类若修改包内容则在此声明。纯消费者（如 Terminal、OSC）返回 `[]`。

示例（`MicrophoneSource`）：
```python
[
  {"name": "audio_data",        "must_have": True,  "description": "原始 PCM 音频字节"},
  {"name": "sample_rate",       "must_have": True,  "description": "采样率（Hz）"},
  {"name": "source_type",       "must_have": True,  "description": "音频源类型（microphone/loopback）"},
  {"name": "source_name",       "must_have": True,  "description": "设备可读名称"},
  {"name": "is_final_segment",  "must_have": True,  "description": "是否为最终语音段"},
  {"name": "is_partial",        "must_have": True,  "description": "是否为流式中间帧"},
  {"name": "is_speech_start",   "must_have": True,  "description": "是否为语音段首帧"},
  {"name": "audio_chunk_idx",   "must_have": True,  "description": "段内帧序号（0-based）"},
  {"name": "timestamp",         "must_have": True,  "description": "帧时间戳（UNIX 秒）"},
]
```

---

#### `get_config_attributes() → list[dict]`

声明本模块接受的**配置参数**，为 GUI 表单动态生成和文档展示提供完整信息。

返回字段 schema（每项为 dict）：

| Key | 类型 | 说明 |
|-----|------|------|
| `name` | `str` | 参数名（对应 `config["params"][name]`） |
| `type` | `ParamType` | 参数类型（影响 GUI 组件选择） |
| `default` | `Any` | 默认值；`None` 表示无默认（必填） |
| `required` | `bool` | 是否为必填项 |
| `description` | `str` | 参数说明 |
| `selectable` | `list \| None` | `ParamType.Select` 时的选项列表，其他类型为 `None` |
| `min` | `Any` | 数值类型的最小值，不适用时为 `None` |
| `max` | `Any` | 数值类型的最大值，不适用时为 `None` |

示例（`VRChatOSCConsumer`）：
```python
[
  {"name": "host",        "type": ParamType.String, "default": "127.0.0.1", "required": False, "description": "OSC 目标 IP",   "selectable": None, "min": None, "max": None},
  {"name": "port",        "type": ParamType.Int,    "default": 9000,        "required": False, "description": "OSC 目标端口",  "selectable": None, "min": 1,    "max": 65535},
  {"name": "trigger_sfx", "type": ParamType.Bool,   "default": False,       "required": False, "description": "通知音效",      "selectable": None, "min": None, "max": None},
  {"name": "max_chars",   "type": ParamType.Int,    "default": 144,         "required": False, "description": "最大字符数",    "selectable": None, "min": 1,    "max": None},
  {"name": "group_by",    "type": ParamType.String, "default": "",          "required": False, "description": "分组 key",      "selectable": None, "min": None, "max": None},
]
```

---

### 各模块 config_attributes 速查

| 模块类 | 注册类型 | 配置参数数量 | 关键必填参数 |
|--------|----------|-------------|-------------|
| `MicrophoneSource` | `microphone` | 7 | — |
| `LoopbackSource` | `loopback` | 7 | — |
| `PacketFilter` | `filter` | 3 | `field` |
| `VolcStreamingSTT` | `volc_streaming_stt` | 7 | — |
| `LocalParaformerSTT` | `local_stt` | 6 | `model_path` |
| `VolcMachineTranslation` | `volc_machine_translation` | 5 | `target_language` |
| `BaiduMachineTranslation` | `baidu_machine_translation` | 4 | `app_id`, `app_key`, `target_language` |
| `TerminalConsumer` | `terminal` | 2 | — |
| `VRChatOSCConsumer` | `osc_vrchat` | 5 | — |

---

`modules/` 目录包含所有具体业务实现，按功能分为四个子包：

```
modules/
├── audio/       PacketProducerModule 实现（音频捕获 + VAD）
├── input/       文字输入来源（GUI 注入与上游透传）
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
2. 450ms 前置窗口判断：窗口内 >=85% 有声帧 → 语音开始（并将判定点之前的 450ms 也包含进最终包，避免吞音）
3. 积累到 450ms 后置窗口 >=80% 无声帧 → 语音结束
4. 超长截断（默认 15s）：在缓冲区找离端点最近的自然停顿拆分，前段发出，后段继续积累（不丢弃）
5. 输出一个 `is_final_segment=True, is_partial=False` 的包

#### 流式模式（`mode="streaming"`）

1. VAD 开始检测到语音（同样会将判定点之前的 450ms 包裹在首块发出防吞音）
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
| `sync_vrc_mic` | `false` | 是否仅在 VRChat 游戏内麦克风开启时向下游发送数据包 |

#### VRChat 麦克风状态同步

`sync_vrc_mic=true` 时，音频源使用 `python-osc` 监听 VRChat 的 OSC 输出：

- 地址：`/avatar/parameters/MuteSelf`
- 本地监听：`127.0.0.1:9001`（VRChat 默认 OSC 输出端口）
- 值为 `true`：游戏内麦克风关闭，不向下游发送音频包
- 值为 `false`：游戏内麦克风开启，允许向下游发送音频包
- 尚未收到状态：按关闭处理，防止在状态未知时误发送

监听器是进程级单例并带引用计数，`MicrophoneSource` 和 `LoopbackSource` 以及多条管道可共享同一个 UDP 端口。录音和 VAD 不会暂停，仅在产出的数据包进入下游前过滤，因此游戏内重新开麦后会自动恢复，无需重载管道。

使用前必须在 VRChat 的 Action Menu 中启用 OSC，且 `127.0.0.1:9001/UDP` 不能被其他 OSC 接收程序独占。

启动日志会明确输出 `VRChat 麦克风状态同步已启用` 或 `sync_vrc_mic=false`。只有配置值为 `true` 时才会继续出现 `正在监听 VRChat 麦克风状态`；已有模块实例不会因为新增 schema 自动改成启用，需在 GUI 编辑模块并打开该开关，或在 `params` 中显式配置。

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
    "vad_mode": 2,
    "sync_vrc_mic": false
  }
}
```

| 参数 | 说明 |
|------|------|
| `device_name` | 麦克风设备名，`null` 使用系统默认麦克风 |
| `sync_vrc_mic` | `true` 时跟随 VRChat 游戏内麦克风开关发送数据包 |

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
    "chunk_ms": 200,
    "sync_vrc_mic": false
  }
}
```

| 参数 | 说明 |
|------|------|
| `process_name` | 目标进程名（如 `"VRChat.exe"`），`null` 使用默认扬声器 |
| `sync_vrc_mic` | `true` 时跟随 VRChat 游戏内麦克风开关发送数据包 |

---

## modules/input/ — 文本输入与透传

### TextInput (text_input.py)

注册类型：`"text_input"`

该模块既可以是流程头（Producer），也可以串联在流程中间。它具备双重功能：
1. **上游透传**：像阀门一般，若上门存在发送给它的普通数据包，它将保持原样透传。
2. **GUI 注入**：配合 GUI `/output` 页面上方的文字输入区，提供交互输入框。用户主动提交的文本将被封装为含有 `text_original`、`is_final_segment=True` 的标准化数据包，并自动混流发往下游。

文字输入区使用模块 `display_name`；数据包的 `source_name` 仍保持原有 `ref_id` 契约，避免改名影响下游逻辑。

> **最佳实践：** 常用于手动发送语句进行翻译、或是在无法捕获游戏声音时直接手动打字。

**Config 参数：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `source_lang` | `"auto"`| 给从 GUI 注入的数据包标记的来源语言类型 |

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
| 处理 | 整段数组**一次性传入** `generate()`，无分块、无流式参数，离线模型直接返回完整文字 | 每积累 `chunk_size[1]*960` 样本（默认 600ms）推理一次 |
| 推荐模型 | 离线批量模型（如 `paraformer-zh`） | 在线流式模型（如 `paraformer-zh-streaming`） |
| 输出 | 一个 `is_partial=False` 包 | 多个 `is_partial=True` + 最后一个 `is_partial=False` |

**音频格式转换：**
- 管道传入 16-bit PCM bytes（mono 16kHz）
- 模型需要 float32 numpy 数组，转换公式：`pcm_int16 / 32768.0`

**文字拼接行为（与云端 API 的关键差异）：**

FunASR 流式模型每次 `generate()` 仅返回当前 chunk 的**增量词语**，而非已识别文字的完整累积（云端 API 通常会返回完整句子）。因此流式模式模块内部维护 `_accumulated_text`，将每个 chunk 的识别结果追加拼接：

| 场景 | `KEY_TEXT_ORIGINAL` 内容 |
|------|--------------------------|
| partial 包（流式中间帧） | 本段语音迄今所有 chunk 结果的**拼接累积** |
| final 包（流式最终帧） | 本段语音完整拼接结果 |

批处理模式（`_infer_full`）调用离线模型一次性推理，直接返回完整文字，无需增量累积。若离线模型内置了 VAD 并拆分为多句，各句文字一并拼接后输出。

示例（流式模式下，模型增量 → 包发出内容）：
```
第1帧 generate() → "你好"       → partial 包: "你好"
第2帧 generate() → "世界"       → partial 包: "你好世界"
最终帧 generate() → ""          → final   包: "你好世界"
```

`_accumulated_text` 在每段语音开始时重置（`is_speech_start=True` 或 `_reset_stream_state()`），段间互不影响。

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
| `model_name` | `"paraformer-zh-streaming"` | 传给 AutoModel 的 model 参数。批处理模式推荐使用离线模型（如 `"paraformer-zh"`）；流式模式使用 `"paraformer-zh-streaming"` |
| `streaming_mode` | `false` | `true` 开启流式推理模式 |
| `chunk_size` | `[0, 10, 5]` | **仅流式模式使用**。FunASR chunk_size，决定单次推理窗口（`chunk_size[1]*960` 样本） |
| `encoder_chunk_look_back` | `4` | **仅流式模式使用**。Encoder 自注意力回看 chunk 数 |
| `decoder_chunk_look_back` | `1` | **仅流式模式使用**。Decoder 交叉注意力回看 chunk 数 |

> **注意：** 使用前需安装 `funasr`：`pip install funasr`。批处理模式（`streaming_mode=false`）可搭配音频源 `mode="batch"`，推荐使用离线 Paraformer 模型；流式模式必须搭配 `mode="streaming"` 及在线流式模型。

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
