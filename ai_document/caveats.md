# 注意事项与开发约定

## 一、模块开发约定

### 1. 新增模块必须继承正确的基类

| 场景 | 继承 |
|------|------|
| 主动产包（音频采集、文件读取等） | `PacketProducerModule` |
| 被动处理队列（识别、翻译、过滤、输出等） | `PacketConsumerModule` |

**禁止**在 `start()` / `stop()` 上覆盖——这两个方法是 `@final`。使用生命周期钩子替代：

```python
# ✗ 错误
def start(self): ...
def stop(self): ...

# ✓ 正确
def on_start(self): ...           # 线程启动前
def on_before_stop(self): ...    # 发出停止信号前
def on_after_stop(self): ...     # 线程退出后（释放资源）
```

### 2. `process_packet` 必须返回 list

即使是纯消费（不向下游发包），也要返回 `[]`，不能返回 `None`：

```python
def process_packet(self, packet):
    print(packet.get(KEY_TEXT_TRANSLATED))
    return []   # ← 不发下游，返回空列表
```

### 3. 不要在 `process_packet` 内部直接调用 `send_to_downstream`

框架的 `_dispatch()` 会自动对 `process_packet` 的返回值调用 `send_to_downstream`。直接调用会导致重复发送。

### 4. 过滤逻辑优先用 `pre_process` 钩子，而非 `process_packet` 内部 `return [packet]`

```python
# ✓ 推荐：pre_process 返回 None 丢弃包（framework 层面，语义清晰）
def pre_process(self, packet):
    return None if packet.is_partial else packet

# 可接受：process_packet 内早返回，但语义略模糊
def process_packet(self, packet):
    if packet.is_partial:
        return []
    ...
```

### 5. 注册新模块类型

在 `core/engine.py` 对应注册表中添加一行：

```python
# 生产者
PRODUCER_REGISTRY["my_source"] = MySourceClass

# 消费者/翻译/过滤
MODULE_REGISTRY["my_module"] = MyModuleClass
```

---

## 二、MessagePacket 使用约定

### 1. 始终使用 KEY 常量，禁止硬编码字符串

```python
# ✗ 错误
packet.set("text_original", text)

# ✓ 正确
from core.packet import KEY_TEXT_ORIGINAL
packet.set(KEY_TEXT_ORIGINAL, text)
```

### 2. `is_partial` 只用 property 访问

```python
# ✓ 正确
packet.is_partial
packet.is_partial = True

# ✗ 不要直接操作 data
packet.data["is_partial"]        # 可读，但绕过 property 语义
packet.get(KEY_IS_PARTIAL)       # 可用（与 property 等价），但推荐用 property
```

### 3. 向下游发包前先 `clone()`

如果要修改包内容再发出，必须先 `clone()` 出新包，**不要修改传入的 source 包**（该包可能同时被其他下游使用）：

```python
def process_packet(self, packet):
    out = packet.clone()          # ← 创建副本
    out.set(KEY_TEXT_TRANSLATED, translated)
    return [out]
```

### 4. `mark_node_time` 由框架自动调用

`send_to_downstream()` 内部已自动调用 `packet.mark_node_time(self._ref_id)`，
模块代码**不需要**手动调用。

---

## 三、config.json 约定

### 1. 敏感信息用环境变量

```json
"api_key": "${VOLC_API_KEY}"
```

不要将真实 API Key 提交到版本控制。

### 2. `_ref_id` / `_display_name` / `pipeline_id` / `pipeline_name` 由 engine 注入

不要在 config 中手动写这些字段，engine 会覆盖。

配置顶层模块定义中的 `display_name` 可以修改；内部 `ref_id` 是稳定路由键，修改显示名称时不得同步改键。GUI 新建或复制模块时会根据初始显示名称自动生成哈希 `ref_id`。

### 3. `entry` 必须是 `PacketProducerModule`

如果 `entry` 指向一个消费者模块，`Pipeline.__post_init__` 会在启动时立即抛出 `TypeError`。

### 4. 注释 key 约定

config.json 中以 `"_comment"` 开头的 key（如 `"_comment_audio"`）会被引擎忽略（只读取已知字段），可随意添加行内注释。

---

## 四、线程与并发安全

### 1. 每个模块运行在独立守护线程

模块的 `_run()` 方法由框架在 `daemon=True` 的线程中调用。进程退出时守护线程自动结束，无需额外清理。

### 2. input_queue 容量为 200

当下游处理速度跟不上上游产包速度时，队列满后新包被**丢弃**并记录 WARNING 日志（`put_nowait` 不阻塞上游）。

调参建议：
- 如频繁看到队列丢弃日志，考虑减少上游产包频率（增大 `chunk_ms`）或优化下游处理速度

### 3. stop 顺序：反拓扑序

`Pipeline.stop()` 按反拓扑序停止（叶节点 → 根节点），确保消费者先停、音频源最后停，避免包在停止过程中堆积在队列里。

哨兵机制：`stop()` 向 `input_queue` 投入 `None`，使阻塞的 `get()` 立即返回并退出循环。若队列已满，投入会静默失败（`_stop_event` 已置位，超时后线程自然退出）。

---

## 五、音频相关

### 1. VAD 灵敏度选择

| `vad_mode` | 适用场景 |
|-----------|---------|
| `0` | 安静环境，噪声极少 |
| `1` | 轻度背景噪声 |
| `2` | 中等噪声（默认） |
| `3` | 高噪声环境（游戏中推荐，减少误触发） |

### 2. 流式模式配套

音频源 `mode="streaming"` 必须搭配 STT 的 `streaming_mode=true`，两边要一致。
批处理/流式混用（如音频源 streaming + STT batch）会导致包类型不匹配，识别效果极差。

### 3. 重采样

soundcard 采集的音频可能不是 16kHz（取决于设备），`VADPacketProducerModule` 内部会自动重采样到 16kHz（webrtcvad 要求）。安装 `scipy` 可获得更高质量的重采样；未安装时退路使用 numpy 线性插值。

### 4. 环回设备仅 Windows WASAPI 支持

`LoopbackSource` 依赖 Windows WASAPI 环回，macOS/Linux 不支持（需要其他方案如 BlackHole、PulseAudio loopback）。

### 5. VRChat 麦克风同步依赖 OSC 输出

`sync_vrc_mic=true` 时监听 `127.0.0.1:9001/UDP` 的 `/avatar/parameters/MuteSelf`。需先在 VRChat 中启用 OSC。若端口已被其他程序占用，监听器无法启动；若尚未收到状态，则安全地视为麦克风关闭，不向下游发包。两个音频模块共享一个监听器，不会在本程序内部重复占用端口。

---

## 六、扩展点速查

| 目标 | 入口 |
|------|------|
| 新增音频源类型 | 继承 `VADPacketProducerModule`，实现 `_create_recorder()` + `_source_name()`，注册到 `PRODUCER_REGISTRY` |
| 新增 STT/MT 服务 | 继承 `PacketConsumerModule`，实现 `process_packet()`，注册到 `MODULE_REGISTRY` |
| 新增输出目标 | 继承 `PacketConsumerModule`，实现 `process_packet()`（返回 `[]`），注册到 `MODULE_REGISTRY` |
| 添加过滤条件 | 在 config.json 中插入 `"type": "filter"` 节点，无需写代码 |
| 双语合并显示 | 对消费者模块配置 `group_by: "timestamp_<stt_ref_id>"`，覆盖 `pre_process()`, `process_packet()`, `post_process()` |
| GUI 实时数据 | `register_gui_callback(fn)` 注册回调，fn 参数为 `(pipeline_name, original, translated)` |
