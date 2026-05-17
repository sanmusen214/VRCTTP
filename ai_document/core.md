# Core 层详解

`core/` 目录是纯框架代码，不含任何业务逻辑。四个文件各司其职：

```
core/
├── packet.py    # 数据包定义
├── module.py    # 模块基类层级
├── pipeline.py  # 单条管道（连线 + 生命周期）
└── engine.py    # 全局引擎（配置加载 + 注册表 + 统一管理）
```

---

## packet.py — MessagePacket

管道中流动的最小信息单元。

```python
@dataclass
class MessagePacket:
    pipeline_id: str          # 所属 pipeline ID
    id: str                   # UUID4，每包唯一
    created_at: datetime      # 创建时间（UTC）
    data: dict[str, Any]      # 所有业务数据以 key-value 存储
    is_partial: bool          # property，读写均操作 data["is_partial"]
```

### 标准 Key 常量

所有模块必须使用以下常量，禁止硬编码字符串：

| 常量 | key 字符串 | 说明 |
|------|-----------|------|
| `KEY_AUDIO_DATA` | `"audio_data"` | bytes，16-bit PCM mono 16kHz |
| `KEY_SAMPLE_RATE` | `"sample_rate"` | int，如 16000 |
| `KEY_SOURCE_TYPE` | `"source_type"` | `"microphone"` \| `"loopback"` |
| `KEY_SOURCE_NAME` | `"source_name"` | 设备名/进程名 |
| `KEY_IS_FINAL_SEGMENT` | `"is_final_segment"` | bool，True 表示完整语音分段结束 |
| `KEY_TEXT_ORIGINAL` | `"text_original"` | 识别出的原文 |
| `KEY_TEXT_TRANSLATED` | `"text_translated"` | 翻译后的文字 |
| `KEY_SOURCE_LANG` | `"source_lang"` | 原文语言代码 |
| `KEY_TARGET_LANG` | `"target_lang"` | 目标语言代码 |
| `KEY_IS_PARTIAL` | `"is_partial"` | bool，True 为流式中间结果 |
| `KEY_IS_SPEECH_START` | `"is_speech_start"` | bool，True 为语音段首帧 |
| `KEY_AUDIO_CHUNK_INDEX` | `"audio_chunk_idx"` | int，流式帧序号（调试） |
| `KEY_TIMESTAMP` | `"timestamp"` | float，音频捕获 UTC 时间戳 |

### is_partial 的设计

`is_partial` 是唯一有 property backing 的字段。不存在双重存储：

```python
packet.is_partial          # 读 data["is_partial"]
packet.is_partial = True   # 写 data["is_partial"]
packet.get("is_partial")   # 同样读 data["is_partial"]，三者一致
```

`__post_init__` 保证 `data["is_partial"]` 始终存在（默认 `False`），`clone()` 通过深拷贝 `data` 自动携带该值。

### 节点时间戳（mark_node_time）

```python
packet.mark_node_time("volc_stt")
# 等价于：packet.data["timestamp_volc_stt"] = time.time()
```

`send_to_downstream()` 在广播前自动调用此方法，写入本模块的 `_ref_id`。
下游 `PacketConsumerModule` 若配置了 `group_by="timestamp_volc_stt"`，则会将同一时间戳的所有分叉包合并为一组渲染（双语显示场景）。

### clone()

单下游：直接传递原包引用（无克隆，零分配）。
多下游：每个下游获得独立深拷贝，UUID 重新生成，`data` 深拷贝（含 `is_partial`、时间戳等所有字段）。

---

## module.py — 模块基类层级

```
BaseModule
├── PacketProducerModule    主动产包（音频源）
└── PacketConsumerModule    被动消费队列（STT / MT / 过滤 / 消费者）
```

### BaseModule

所有模块的根类。

**@final 方法（不可覆盖）：**

| 方法 | 说明 |
|------|------|
| `add_downstream(module)` | 添加一个下游模块 |
| `send_to_downstream(packet)` | 打时间戳后广播至所有下游 |
| `start()` | `on_start()` → 启动后台线程 |
| `stop()` | `on_before_stop()` → 置位 stop_event → 投入 None 哨兵 → join → `on_after_stop()` |

**生命周期钩子（子类可覆盖，默认空实现）：**

| 钩子 | 调用时机 |
|------|---------|
| `on_start()` | 线程启动前，适合连接 WebSocket、初始化 asyncio loop 等 |
| `on_before_stop()` | 发出停止信号前，适合发送"结束帧"给服务器 |
| `on_after_stop()` | 线程退出后，适合关闭 Session、释放资源 |

**关键属性：**

| 属性 | 说明 |
|------|------|
| `module_id` | 完整 ID，如 `"vrchat_volc_streaming.volc_stt"`，用于日志 |
| `_ref_id` | 本地引用 ID，如 `"volc_stt"`，来自 `config["_ref_id"]`（由 engine 注入） |
| `input_queue` | `Queue(maxsize=200)`，生产者写入，消费者读取 |
| `_stop_event` | `threading.Event()`，置位表示请求停止 |

### PacketProducerModule

```python
@final def _run(self):
    for packet in self.produce_packets():
        if self._stop_event.is_set(): break
        self.send_to_downstream(packet)

@abstractmethod def produce_packets(self): ...  # 生成器
```

子类只需实现 `produce_packets()`，当 `_stop_event` 被置位时应尽快退出生成器。

### PacketConsumerModule

完整处理链：

```
input_queue.get()
    │
    ▼
_dispatch(packet)，根据有无 group_by 整合先前本地记录的包
    ├── pre_process(packet)          ← 可覆盖，返回 None 则丢弃
    ├── process_packet(packet)       ← 必须实现，返回 list[MessagePacket]
    ├── post_process(results)        ← 可覆盖，修改结果列表
    └── send_to_downstream(out)      ← 对每个结果包广播
```

**Config 参数：**

| 参数 | 说明 |
|------|------|
| `group_by` | 分组 key，如 `"timestamp_volc_stt"`；空字符串表示不分组 |

**向后兼容别名（文件末尾）：**

```python
AudioSourceModule = PacketProducerModule
TranslationModule = PacketConsumerModule
ConsumerModule    = PacketConsumerModule
```

---

## pipeline.py — Pipeline

单条翻译管道，一个 `Pipeline` 对应 `config.json` 中一条 `pipelines[]` 配置项。

```python
@dataclass
class Pipeline:
    pipeline_id: str
    name: str
    all_modules: dict[str, BaseModule]  # {ref_id: 模块实例}
    routes: dict[str, list[str]]        # 邻接表：{from_ref: [to_ref, ...]}
    entry: str                          # 根节点 ref_id（必须是 PacketProducerModule）
```

### 主要方法

| 方法 | 说明 |
|------|------|
| `build()` | 按 routes 邻接表调用 `add_downstream()` 连线，只执行一次 |
| `start()` | 按拓扑序（DFS 后序翻转）逐模块调用 `module.start()` |
| `stop()` | 按反拓扑序（先停叶节点）逐模块调用 `module.stop()` |
| `audio_source` | property，返回 entry 节点（`PacketProducerModule`） |
| `translation_chain` | property，返回所有 `PacketConsumerModule` 列表（顺序不定） |

---

## engine.py — PipelineEngine

### 模块注册表

新增模块类型只需在此注册，无需修改其他代码：

```python
PRODUCER_REGISTRY: dict[str, type[PacketProducerModule]] = {
    "microphone": MicrophoneSource,
    "loopback":   LoopbackSource,
}

MODULE_REGISTRY: dict[str, type[PacketConsumerModule]] = {
    "volc_streaming_stt":     VolcStreamingSTT,
    "volc_machine_translation": VolcMachineTranslation,
    "terminal":               TerminalConsumer,
    "osc_vrchat":             VRChatOSCConsumer,
    "filter":                 PacketFilter,
}

# 向后兼容别名
PRODUCER_REGISTRY = PRODUCER_REGISTRY
MODULE_REGISTRY  = MODULE_REGISTRY
MODULE_REGISTRY     = MODULE_REGISTRY
```

### 配置加载流程

1. `load_config()`：读取 JSON，递归替换所有 `${ENV_VAR}` 占位符
2. `build_all()`：遍历 `pipelines[]` 中 `enabled=true` 的配置
3. 对每条 pipeline：
   - 收集所有 `ref_id`（entry + routes 中出现的所有节点）
   - 从全局 `modules` 字典查配置，按 `type` 查注册表实例化
   - engine 自动注入 `_ref_id`、`pipeline_id`、`pipeline_name` 到 params
   - 构建 `Pipeline` 对象并调用 `build()`（连线）

### engine 注入的隐式参数

所有模块在实例化时，engine 会自动往 `config` 中注入：

| key | 值 |
|-----|----|
| `_ref_id` | 模块在配置中的 ref_id（如 `"volc_stt"`） |
| `pipeline_id` | 所属 pipeline 的 id（如 `"vrchat_volc_streaming"`） |
| `pipeline_name` | 所属 pipeline 的 name（仅 MODULE_REGISTRY 模块） |

### 热重载（reload_config）

调用 `stop_all()` → `load_config()` → `build_all()` → `start_all()`，实现无停机配置更新。
