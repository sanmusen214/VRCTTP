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
    # 路由上下文（PacketProducerModule 注入，clone 时浅复制）
    _pipeline_routes: dict[str, list[str]]  # ref_id → [next_ref_id, ...]
    _pipeline_modules: dict[str, BaseModule] # ref_id → 模块实例
```

`_pipeline_routes` 和 `_pipeline_modules` 由生产者模块在 `_run()` 中写入，携带本条 pipeline 的完整路由图。`send_to_downstream()` 优先使用这两个字段实现动态寻路，不再依赖静态的 `_downstream` 列表。

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
`_pipeline_routes` / `_pipeline_modules` 两个路由字段**浅复制（共享引用）**，分叉后的所有包仍遵循相同路由图。

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
| `send_to_downstream(packet)` | 打时间戳后按包内路由分发至下一跳 |
| `start()` | `on_start()` → 启动后台线程（引用计数） |
| `stop()` | `on_before_stop()` → 置位 stop_event → 投入 None 哨兵 → join → `on_after_stop()`（引用计数） |

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
| `input_queue` | `Queue(maxsize=pipeline_queue_size)`，大小在全局 `config` 可配（默认 2）。满载后自动丢弃旧包塞入新包，避免拥塞延时。 |
| `_stop_event` | `threading.Event()`，置位表示请求停止 |

### PacketProducerModule

```python
@final def _run(self):
    for packet in self.produce_packets():
        if self._stop_event.is_set(): break
        # 仅对新建包注入路由；转发包已携带正确路由，不覆盖
        if not packet._pipeline_routes:
            packet._pipeline_routes = self._pipeline_routes
            packet._pipeline_modules = self._pipeline_modules
        self.send_to_downstream(packet)

def set_pipeline_context(routes, modules): ...  # 由 Pipeline.build() 对所有生产者调用
@abstractmethod def produce_packets(self): ...  # 生成器
```

子类只需实现 `produce_packets()`，当 `_stop_event` 被置位时应尽快退出生成器。

`Pipeline.build()` 对 `all_modules` 中所有具有 `set_pipeline_context` 的模块（即所有 `PacketProducerModule`）都调用该方法，
注入本 pipeline 的完整路由图。这包括入口音频源和 DAG 中间的所有生产者节点（如 `TextInput`）。

`_run()` 对包的路由注入规则：
- **包已有路由信息**（转发自上游的包）：保持原有路由不覆盖，继续沿原 pipeline 路由流动。
- **包无路由信息**（本模块新建的包）：写入本 pipeline 路由。

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
| `build()` | 校验路由图，对 `all_modules` 中**所有** `PacketProducerModule`（入口及中间生产者如 `TextInput`）调用 `set_pipeline_context(routes, all_modules)` 注入路由上下文，只执行一次。**不调用 `add_downstream()`**，路由由包携带。 |
| `start()` | 按拓扑序（DFS 后序翻转）逐模块调用 `module.start()` |
| `stop()` | 按反拓扑序（先停叶节点）逐模块调用 `module.stop()` |
| `audio_source` | property，返回 entry 节点（`PacketProducerModule`） |
| `translation_chain` | property，返回所有 `PacketConsumerModule` 列表（顺序不定） |

### 包驱动路由（Packet-Driven Routing）

包在 `PacketProducerModule._run()` 中被打上本 pipeline 的路由信息：

```python
packet._pipeline_routes  # dict[str, list[str]]  路由邻接表
packet._pipeline_modules # dict[str, BaseModule]  ref_id → 实例
```

`BaseModule.send_to_downstream(packet)` 直接按 `packet._pipeline_routes.get(self._ref_id)` 寻找下一跳入队，无任何静态连线。

`clone()` 对 `_pipeline_routes` / `_pipeline_modules` 做**浅复制（共享引用）**，
分叉后的所有包仍遵循同一路由图，零额外开销。

**中间生产者节点**（如 `TextInput` 接在 DAG 中间）同样是 `PacketProducerModule`，`build()` 会对其注入路由。
它 yield 的两类包处理方式不同：
- **新建包**（GUI 文字输入）：`_pipeline_routes` 为空，`_run()` 写入本 pipeline 路由。
- **转发包**（上游透传）：已携带正确路由，`_run()` 不覆盖，继续沿原路由流动。

---

## engine.py — PipelineEngine

### 全局模块实例缓存（DAG 格式专用）

`PipelineEngine` 维护 `_global_module_cache: dict[str, BaseModule]`（按 `ref_id` 缓存）。

在 `_build_dag_pipeline()` 中：
- **音频源**（`PacketProducerModule`）：每条 pipeline 独立实例化（持有各自的路由上下文），**不进缓存**。
- **消费/翻译模块**（`PacketConsumerModule`）：首次创建后存入缓存；后续 pipeline 引用相同 `ref_id` 时直接复用已有实例。

重型模块（如 `LocalParaformerSTT`）的模型权重只加载一次，所有 pipeline 共享同一实例。包通过内嵌路由信息各自流向正确的下游，实例内部按 `pipeline_id` 隔离流式状态，彼此不串流。

`reload_config()` 会先调用 `_global_module_cache.clear()` 再重建，确保热重载后重新创建实例。

### 共享实例生命周期（引用计数）

`BaseModule.start()` / `stop()` 内置引用计数（`_start_count`，线程安全）：

| 调用 | 行为 |
|------|------|
| `start()`，`_start_count` 0→1 | 真正启动线程，调用 `on_start()` |
| `start()`，`_start_count` 1→N | 仅递增计数，直接返回（线程已在运行） |
| `stop()`，`_start_count` N→1 | 仅递减计数，直接返回（其他 pipeline 仍在用） |
| `stop()`，`_start_count` 1→0 | 真正停止线程，调用 `on_before_stop()` / `on_after_stop()` |

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
