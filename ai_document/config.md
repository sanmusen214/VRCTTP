# config.json 配置说明

`config.json` 定义所有模块实例和 pipeline 拓扑。GUI 对模块和管道的增删改最终也会写回这个文件。

## 顶层结构

```json
{
  "pipeline_queue_size": 2,
  "modules": {},
  "pipelines": [],
  "gui": {
    "enabled": true,
    "host": "127.0.0.1",
    "port": 8082
  }
}
```

| 字段 | 说明 |
|------|------|
| `pipeline_queue_size` | 模块输入队列大小，越小越实时，越大越能缓冲 |
| `modules` | 全局模块实例注册表 |
| `pipelines` | pipeline 列表 |
| `gui` | Web GUI 配置 |

## modules

`modules` 以稳定 `ref_id` 为键定义模块实例。

```json
"modules": {
  "my_module_ref_id": {
    "display_name": "GUI 显示名称",
    "type": "模块注册类型",
    "params": {}
  }
}
```

### ref_id 与 display_name

| 字段 | 用途 |
|------|------|
| `ref_id` | 配置对象的 key，用于路由、缓存和时间戳 |
| `display_name` | GUI 展示名称，可修改，不影响路由 |

GUI 新建模块时会生成 `mod_<sha256(display_name)[:16]>` 作为 `ref_id`。复制模块时会先生成唯一显示名，再生成新的 `ref_id`。

### 支持的 type

| type | 说明 |
|------|------|
| `microphone` | 麦克风音频源 |
| `loopback` | 系统音频输出设备对应的 loopback |
| `text_input` | GUI 文本输入 |
| `volc_streaming_stt` | 火山引擎 STT |
| `local_stt` | 本地 FunASR STT |
| `volc_machine_translation` | 火山引擎机器翻译 |
| `baidu_machine_translation` | 百度翻译 |
| `llm_openai_api_call` | 通用 LLM JSON API 翻译 |
| `filter` | 字段过滤器 |
| `terminal` | 终端输出 |
| `osc_vrchat` | VRChat OSC 输出 |

GUI 中模块会按管道流向分组展示和选择：

| 分组 | type |
|------|------|
| 输入源 | `microphone`、`loopback`、`text_input` |
| 语音识别 | `volc_streaming_stt`、`local_stt` |
| 过滤处理 | `filter` |
| 翻译 | `volc_machine_translation`、`baidu_machine_translation`、`llm_openai_api_call` |
| 输出 | `terminal`、`osc_vrchat` |
| 其他 | 未显式归类的新模块类型 |

## pipelines

每条 pipeline 是一张 DAG。

```json
{
  "id": "pipeline_id",
  "name": "显示名称",
  "enabled": true,
  "graph": {
    "entry": "source_ref_id",
    "routes": {
      "source_ref_id": ["next_ref_id"],
      "next_ref_id": ["consumer_ref_id"]
    }
  }
}
```

规则：

- `id` 必须唯一。
- `entry` 必须指向 producer 模块，例如 `microphone`、`loopback`、`text_input`。
- `routes` 中出现的所有 ref_id 必须在 `modules` 中存在。
- 一个 from 可以指向多个 to，实现 fan-out。
- `enabled=false` 的 pipeline 不会启动。
- GUI 的管道编辑器使用拖拽画布编辑拓扑，但保存时仍只写入 `graph.entry` 和 `graph.routes`。保存会自动丢弃未从入口节点连通的离散节点。
- GUI 画布中的节点位置、节点宽度、连线选中状态等只属于编辑器界面状态，不写入 `config.json`。

## 环境变量占位符

默认 `.env` 位于应用目录：打包运行时与 exe 同级，源码运行时位于项目根目录，不读取 PyInstaller 的 `_internal/.env`。程序内置以下最低字段，文件不存在时会创建，已有文件缺字段时会以空值补齐，同时保留原有字段和值：

- `VOLC_API_KEY`
- `BAIDU_APP_ID`
- `BAIDU_APP_KEY`
- `llm_api_key`

这些字段不是单纯的字符串元组，而是记录在 `runtime_paths.py` 的 JSON 兼容列表 `MINIMUM_ENV_KEYS` 中。每一项包含：

```json
{
  "key": "字段名称",
  "description": "中文作用与获取方法（Markdown）"
}
```

补齐 `.env`、判断首次配置状态以及 GUI 获取说明均使用这份元数据。GUI 展示提醒时按字段名第一个 `_` 之前的部分分组，因此 `BAIDU_APP_ID` 和 `BAIDU_APP_KEY` 会合并为 `BAIDU_APP_ID / BAIDU_APP_KEY` 一组。

普通配置字符串支持 `${ENV_VAR}`：

```json
"api_key": "${VOLC_API_KEY}"
```

如果环境变量不存在，engine 会保留原占位符并记录 warning。

在 GUI `/env` 页面保存 `.env` 时，变量会立即写入当前进程环境，并触发 `engine.reload_config()`。因此普通配置中的 `${ENV_VAR}` 可以不重启应用直接应用到重新构建后的管道。

## 默认配置初始化

未传入 `--config` 时，程序使用应用目录下的 `config.json`。如果该文件不存在，则将应用目录下的 `tmp/example_config.json` 重命名并移动到同级 `config.json`，随后读取它。若两者都不存在，配置加载会明确失败。显式传入 `--config` 时不执行这套默认模板逻辑。

`package.py` 不再复制或净化 `.env`；它会把项目根目录的 `config.json` 复制到打包结果的 `tmp/example_config.json`，因此 `tmp` 与 exe 同级。

`llm_openai_api_call` 的 `headers_b64` 和 `payload_b64` 是 base64 字符串，engine 不会看到里面的 `${llm_api_key}`；该模块会在运行时解码后自行替换。

## 常用模块配置示例

### 麦克风

```json
"mic": {
  "display_name": "麦克风",
  "type": "microphone",
  "params": {
    "sample_rate": 16000,
    "vad_mode": 3,
    "mode": "streaming",
    "chunk_ms": 200,
    "sync_vrc_mic": false
  }
}
```

### 系统音频环回

```json
"vrchat_audio": {
  "display_name": "VRChat 音频",
  "type": "loopback",
  "params": {
    "device_name": "__default_system_audio__",
    "sample_rate": 16000,
    "vad_mode": 3,
    "mode": "streaming",
    "chunk_ms": 200
  }
}
```

### 火山 STT

```json
"volc_stt": {
  "display_name": "火山流式识别",
  "type": "volc_streaming_stt",
  "params": {
    "api_key": "${VOLC_API_KEY}",
    "resource_id": "volc.seedasr.sauc.duration",
    "language": "",
    "streaming_mode": true
  }
}
```

### 只放行最终包

```json
"final_only": {
  "display_name": "最终结果过滤",
  "type": "filter",
  "params": {
    "field": "is_partial",
    "pass_when": false
  }
}
```

### 百度翻译

```json
"baidu_en": {
  "display_name": "百度翻译到英文",
  "type": "baidu_machine_translation",
  "params": {
    "app_id": "${BAIDU_APP_ID}",
    "app_key": "${BAIDU_APP_KEY}",
    "source_language": "auto",
    "target_language": "en"
  }
}
```

### LLM 翻译

```json
"llm_en": {
  "display_name": "LLM 翻译到英文",
  "type": "llm_openai_api_call",
  "params": {
    "target_language": "english",
    "api_url": "https://ark.cn-beijing.volces.com/api/v3/responses",
    "headers_b64": "base64 encoded JSON object",
    "payload_b64": "base64 encoded JSON text"
  }
}
```

建议通过 GUI 编辑 LLM headers 和 payload。GUI 会自动处理 base64 编码。

默认 headers 明文：

```json
{
  "Authorization": "Bearer ${llm_api_key}",
  "Content-Type": "application/json"
}
```

payload 明文中用 `%{original}` 表示上游识别文本。

### 终端输出

```json
"terminal": {
  "display_name": "终端输出",
  "type": "terminal",
  "params": {
    "color": true
  }
}
```

### VRChat OSC 输出

```json
"osc": {
  "display_name": "VRChat 输出",
  "type": "osc_vrchat",
  "params": {
    "host": "127.0.0.1",
    "port": 9000,
    "trigger_sfx": false,
    "template": "{translated}",
    "max_chars": 144
  }
}
```

## 完整 pipeline 示例

```json
{
  "id": "vrchat_audio_to_english",
  "name": "VRChat 音频翻译到英文",
  "enabled": true,
  "graph": {
    "entry": "vrchat_audio",
    "routes": {
      "vrchat_audio": ["volc_stt"],
      "volc_stt": ["final_only"],
      "final_only": ["llm_en"],
      "llm_en": ["terminal", "osc"]
    }
  }
}
```

## GUI 配置

```json
"gui": {
  "enabled": true,
  "host": "127.0.0.1",
  "port": 8082
}
```

`enabled=false` 时不启动 Web GUI，管道仍可运行。

## 配置编辑注意事项

- 不要手动写 `_ref_id`、`_display_name`、`pipeline_id`、`pipeline_name`，这些由 engine 注入。
- API Key 建议放入环境变量或 `.env`。
- 修改配置文件后，需要重启程序或在 GUI 首页点击“重载所有配置”。
- 在 GUI 环境变量页修改 `.env` 后会自动保存并热重载，无需重启程序。
- `display_name` 可以改，`ref_id` 作为路由键应保持稳定。
### 桌面半透明翻译窗口

`desktop_overlay` 是纯输出消费者，可与 `terminal`、`osc_vrchat` 并联。
它只记录 `is_partial=false` 的完整句子，并把最新结果放在窗口顶部。
窗口可由系统边框拖动和缩放，内容区域支持滚轮查看历史。
该类型是软件级单例，`modules` 中最多定义一个实例；它随软件而不是 Pipeline
启动和停止。管道热重载不会重建窗口，配置参数会在线应用，窗口历史继续保留。
软件启动加载配置时，`core/default_modules.py` 会遍历通用 `DEFAULT_MODULES`
声明列表。如果 `modules` 中没有符合某项 `match` 条件的实例，就按该项
`definition` 新建模块并立即写回 `config.json`。桌面翻译窗口是当前默认声明之一。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `opacity` | `0.78` | 整个窗口不透明度，范围 0.1-1.0 |
| `font_size` | `20` | 翻译历史文字大小 |
| `width` / `height` | `720` / `360` | 窗口首次创建时的初始尺寸 |
| `topmost` | `true` | 是否保持在其他窗口上方 |
| `history_size` | `30` | 保留的完整句子数量，允许 1-30，超过 30 会被运行时限制为 30 |
| `group_by` | `timestamp_中间件-GUI输入文字` | 多语言分支公共祖先时间戳 |
