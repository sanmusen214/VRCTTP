# Core 层说明

`core/` 是项目框架层，不直接包含语音识别、翻译或输出业务。它定义数据包、模块生命周期、管道路由和配置加载机制。

```text
core/
├── packet.py           # MessagePacket 和标准字段常量
├── module.py           # BaseModule / Producer / Consumer 基类
├── pipeline.py         # 单条 DAG 管道
├── engine.py           # 配置加载、模块注册、管道管理
└── module_identity.py  # ref_id / display_name 兼容与生成
```

## MessagePacket

`MessagePacket` 是管道中流动的最小信息单元。

核心字段：

| 字段 | 说明 |
|------|------|
| `pipeline_id` | 所属 pipeline ID |
| `id` | 包 UUID |
| `created_at` | 创建时间 |
| `data` | 业务字段字典 |
| `is_partial` | property，读写 `data["is_partial"]` |
| `_pipeline_routes` | 当前管道的路由邻接表 |
| `_pipeline_modules` | 当前管道的模块实例表 |

### 标准字段常量

所有模块应使用 `core.packet` 中的常量，避免硬编码字符串。

| 常量 | key | 说明 |
|------|-----|------|
| `KEY_AUDIO_DATA` | `audio_data` | 16-bit PCM mono 音频 bytes |
| `KEY_SAMPLE_RATE` | `sample_rate` | 采样率 |
| `KEY_SOURCE_TYPE` | `source_type` | `microphone` / `loopback` 等 |
| `KEY_SOURCE_NAME` | `source_name` | 设备名或来源名 |
| `KEY_IS_FINAL_SEGMENT` | `is_final_segment` | 是否为语音段最终包 |
| `KEY_TEXT_ORIGINAL` | `text_original` | 识别或输入原文 |
| `KEY_TEXT_TRANSLATED` | `text_translated` | 翻译结果 |
| `KEY_SOURCE_LANG` | `source_lang` | 源语言标记 |
| `KEY_TARGET_LANG` | `target_lang` | 目标语言标记 |
| `KEY_IS_PARTIAL` | `is_partial` | 是否为流式中间结果 |
| `KEY_IS_SPEECH_START` | `is_speech_start` | 是否为新语音段首帧 |
| `KEY_AUDIO_CHUNK_INDEX` | `audio_chunk_idx` | 流式音频帧序号 |
| `KEY_TIMESTAMP` | `timestamp` | 捕获时间戳 |

### 克隆与路由

`packet.clone()` 会深拷贝 `data` 并生成新的包 ID，但浅拷贝 `_pipeline_routes` 和 `_pipeline_modules`。这样 fan-out 分支可以独立修改业务字段，又继续共享同一份路由上下文。

`BaseModule.send_to_downstream()` 会在发包前调用 `packet.mark_node_time(self._ref_id)`，写入 `timestamp_<ref_id>`。下游消费者可通过 `group_by` 使用该时间戳合并多路翻译结果。

## 模块基类

模块分为两类：

| 基类 | 说明 |
|------|------|
| `PacketProducerModule` | 主动产包，例如音频源、`TextInput` |
| `PacketConsumerModule` | 被动消费队列，例如 STT、翻译、过滤、输出 |

二者都继承 `BaseModule`。

### BaseModule 生命周期

`start()` 和 `stop()` 是 `@final`，子类不要覆盖。需要初始化或清理时实现钩子：

| 钩子 | 时机 |
|------|------|
| `on_start()` | 工作线程启动前 |
| `on_before_stop()` | 设置停止信号前 |
| `on_after_stop()` | 工作线程退出后 |

`BaseModule` 支持共享实例引用计数。多个 pipeline 复用同一个 consumer 实例时，第一次 `start()` 才真正启动线程，最后一次 `stop()` 才真正停止线程。

### Producer 运行逻辑

`PacketProducerModule._run()` 迭代 `produce_packets()`：

1. 对新建包注入当前 pipeline 的路由上下文。
2. 对透传包保留原有路由上下文。
3. 调用 `send_to_downstream()` 广播到下一跳。

这也是 `TextInput` 可以既作为入口又作为中间透传节点的原因。

### Consumer 运行逻辑

`PacketConsumerModule._run()` 从 `input_queue` 取包，处理链为：

```text
pre_process(packet)
  -> process_packet(packet)
  -> post_process(results)
  -> send_to_downstream(out_packet)
```

子类必须实现 `process_packet()`，并始终返回 `list[MessagePacket]`。

## ParamType

`ParamType` 描述模块配置参数类型，供 GUI 动态表单使用。

| 类型 | 用途 |
|------|------|
| `String` | 普通文本 |
| `Int` / `Float` | 数值输入 |
| `Bool` | 开关 |
| `Password` | 密码输入 |
| `Select` | 下拉选择 |
| `DirPath` / `FilePath` | 路径输入 |
| `List` | JSON 数组 |
| `LanguageCode` | 语言代码 |
| `HeaderPairsB64` | GUI 明文编辑 headers，配置中 base64 存储 JSON object |
| `JsonTextB64` | GUI 明文编辑 JSON 文本，配置中 base64 存储 text |

`HeaderPairsB64` 和 `JsonTextB64` 当前主要用于 `llm_openai_api_call`。

## Pipeline

`Pipeline` 表示一条 DAG 管道：

| 字段 | 说明 |
|------|------|
| `pipeline_id` | 管道 ID |
| `name` | 显示名称 |
| `entry` | 入口模块 ref_id，必须是 producer |
| `routes` | 路由邻接表 |
| `all_modules` | 管道引用的所有模块实例 |

`Pipeline.build()` 会校验入口和路由，并向所有 producer 注入路由上下文。运行时不保存静态下游列表，包自身携带路由信息。

## PipelineEngine

`PipelineEngine` 负责：

1. 读取配置。
2. 替换 `${ENV_VAR}` 环境变量占位符。
3. 将配置中的 `type` 映射为模块类。
4. 实例化模块并注入隐式参数。
5. 构建、启动、停止和热重载 pipeline。

### 模块注册表

生产者注册在 `PRODUCER_REGISTRY`，消费者注册在 `MODULE_REGISTRY`。

当前主要类型：

```python
PRODUCER_REGISTRY = {
    "microphone": MicrophoneSource,
    "loopback": LoopbackSource,
    "text_input": TextInput,
}

MODULE_REGISTRY = {
    "volc_streaming_stt": VolcStreamingSTT,
    "local_stt": LocalParaformerSTT,
    "volc_machine_translation": VolcMachineTranslation,
    "baidu_machine_translation": BaiduMachineTranslation,
    "llm_openai_api_call": LLMOpenAIAPICall,
    "filter": PacketFilter,
    "terminal": TerminalConsumer,
    "osc_vrchat": VRChatOSCConsumer,
}
```

### 隐式配置注入

实例化模块时，engine 会自动向模块 config 注入：

| key | 说明 |
|-----|------|
| `_ref_id` | 模块在全局 `modules` 中的稳定 ID |
| `_display_name` | GUI 显示名称 |
| `pipeline_id` | 所属 pipeline ID |
| `pipeline_name` | 所属 pipeline 名称 |
| `_queue_size` | 输入队列大小 |

这些字段不需要用户手动写入 `config.json`。

## 模块身份

`module_identity.py` 负责稳定的模块身份策略：

- `ref_id` 用于路由和缓存，不展示给普通用户。
- `display_name` 用于 GUI 展示，可修改。
- GUI 新建模块时生成 `mod_<sha256(display_name)[:16]>` 作为 `ref_id`。
- 修改 `display_name` 不会重算 `ref_id`，因此不会破坏已有路由。

## 热重载

`engine.reload_config()` 的流程：

```text
stop_all()
  -> clear global module cache
  -> load_config()
  -> build_all()
  -> start_all()
```

GUI 保存配置后，需要显式点击重载按钮，改动才会作用到正在运行的 pipeline。
