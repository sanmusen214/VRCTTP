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
- `_queue_policy`
- `_queue_options`

它们由 `PipelineEngine` 注入。

### ref_id 不要随意改

`ref_id` 是 `modules` 对象的 key，也是 pipeline 路由使用的 ID。改它会破坏 routes。需要改名时修改 `display_name`。

### entry 必须是 producer

`graph.entry` 必须指向 `microphone`、`loopback` 或 `text_input` 等 producer。指向 consumer 会导致 pipeline 构建失败。

## 运行时注意事项

### 应用目录中的可写配置

打包版的 `.env`、`config.json` 和 `tmp/` 都以 exe 所在目录为基准，不要把可编辑文件放进 `_internal`。发布包仅携带 `tmp/example_config.json`；首次启动会把它移动成 exe 同级的 `config.json`。因此程序目录必须对当前用户可写。

最低环境变量的名称、中文作用和 Markdown 获取说明统一维护在 `runtime_paths.py` 的 `MINIMUM_ENV_KEYS` JSON 兼容列表中。新增最低字段时不要只修改 GUI；更新该列表即可让文件补齐、空值判断和提醒内容共享同一数据源。字段提醒会按第一个 `_` 之前的前缀自动分组。

### 版本与更新器

- 只在 `version.py` 修改 `version_str`，不要在 `package.py` 或 GUI 再维护独立版本号。
- `settings/software_config.json` 位于应用目录，主程序启动时会同步 `NOWVERSION` 并保留 `SEC_KEY_M`、`ENCRYPT_KEY` 等更新源配置。
- 在线检查在后台线程运行；网络失败只记录日志，不阻止主程序工作。
- 首页版本入口必须始终可用。检查未完成或失败时使用 `version.py.release_info`；
  无新版时使用线上源返回的最新 release notes；只有 `has_new_version=true`
  才显示“立即更新”并启用橙色脉冲提醒。
- 更新按钮只启动应用目录中的 `VRCTTP_UPDATE.exe`，不会在主进程内覆盖文件。启动成功后 GUI 会提示用户并等待 3 秒，再通过共享线程事件请求主线程调用 `PipelineEngine.shutdown()` 后退出；启动失败时不得触发自动退出。
- 发布包必须同时包含固定名称的 `VRCTTP.exe` 和 `VRCTTP_UPDATE.exe`。`package.py` 会依次使用 `main.spec` 与 `update.spec` 构建，并在重命名最终目录前放置两者。
- 主程序使用 PyInstaller `onedir` 模式，`VRCTTP.exe` 不是可以脱离 `_internal` 独立运行的单文件程序。Tkinter 初始化至少依赖 `_internal/_tcl_data/` 和 `_internal/_tk_data/`，不能只更新 exe。
- 更新器放置完成后，打包脚本会通过 `zipfile` 生成同级 `VRCTTP{version_str}_update.zip`。归档必须包含 `VRCTTP_UPDATE.exe`、`VRCTTP.exe`、`_internal/_tcl_data/` 和 `_internal/_tk_data/`；两个数据目录均递归打包并保留相对于打包根目录的路径。
- `package.py` 在创建更新 ZIP 前会检查上述两个数据目录。任一目录不存在时必须终止打包，不能生成缺少 Tcl/Tk 运行数据的更新包。

### 队列大小

`pipeline_queue_size` 默认较小。普通模块优先保证实时性，队列满时会清理
旧包。流式本地 STT 是例外：该模块由 `core/runtime_policies.py` 自动装配
`coalesce_streaming_audio` 策略，队列大小只是开始合并的软阈值。

同段音频积压超过 3 秒时会输出告警，之后按 6、12、24 秒倍增节流。
这个机制能防止背景噪声被 VAD 误判后产生的大量小包被静默丢弃，但如果
模型长期推理速度低于实时速度，无损缓冲的延迟仍会持续增长。此时应降低
模型计算量、调整麦克风/VAD，或改用批处理模式，不应再依赖丢弃音频追赶进度。

`SoundDeviceRecorder` 会对 PortAudio 输入溢出按 1、2、4、8... 次节流记录。
该告警表示音频在进入 Pipeline 之前就可能已经缺损，与模型识别精度无关。

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

项目主要面向 Windows。`MicrophoneSource` 使用 `sounddevice` 采集麦克风；`LoopbackSource` 使用 `soundcard` 从系统音频输出设备获取 WASAPI loopback。macOS/Linux 需要额外音频路由方案。

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
## 软件级服务生命周期

不要在 `DesktopOverlayConsumer.on_start()` / `on_after_stop()` 中管理 Tk 窗口。
窗口由 `DesktopOverlayService.instance()` 唯一持有，`PipelineEngine.start_all()`
负责确保它已启动，`PipelineEngine.shutdown()` 负责最终关闭。普通配置重载只
调用 `stop_all()`，不得销毁该服务，否则切换 Pipeline 会造成窗口闪烁和历史丢失。

窗口的系统关闭操作使用 `withdraw()` 隐藏而不是销毁 Tk。服务通过线程安全事件
维护可见状态，`ensure_visible()` 在已显示时必须保持幂等；隐藏时使用
`deiconify()` 恢复。内建模块默认值统一维护在 `core/default_modules.py`，
不要在首页或引擎中复制一份默认参数。

桌面窗口渲染不得恢复成“每次清空整个 Text 后重绘全部历史”的方式。待渲染状态
必须按分组合并，Tk 单轮处理数量必须有上限；界面使用 Text tag 增量插入、更新和
删除。窗口历史硬上限为 30 条，新增第 31 条时删除文本尾部最旧记录，避免长时间
运行后 Text 内容和单次渲染成本持续增长。待渲染分组也最多保留 30 个，防止窗口
线程短暂繁忙后继续追赶已超出可见历史范围的旧结果。

新增需要自动补齐的模块时，只向 `DEFAULT_MODULES` 追加声明：

```python
{
    "ref_id": "建议的模块键",
    "match": {"type": "模块类型"},
    "definition": {
        "type": "模块类型",
        "display_name": "显示名称",
        "params": {},
    },
}
```

补全流程会逐项检查 `match` 的所有字段。已有匹配实例时保留用户配置；缺失时
深拷贝 `definition`；建议 `ref_id` 冲突时自动追加 `_2`、`_3`。因此增加默认项
不应再修改 `ensure_default_modules()` 或 `PipelineEngine`。
