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

## 环境变量占位符

普通配置字符串支持 `${ENV_VAR}`：

```json
"api_key": "${VOLC_API_KEY}"
```

如果环境变量不存在，engine 会保留原占位符并记录 warning。

在 GUI `/env` 页面保存 `.env` 时，变量会立即写入当前进程环境，并触发 `engine.reload_config()`。因此普通配置中的 `${ENV_VAR}` 可以不重启应用直接应用到重新构建后的管道。

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
