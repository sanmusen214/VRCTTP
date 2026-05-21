# config.json 配置文件说明

## 顶层结构

```json
{
  "modules":   { ... },   // 全局模块注册表（所有模块在此统一定义）
  "pipelines": [ ... ],   // 管道拓扑列表
  "gui":       { ... }    // Web GUI 配置
}
```

---

## modules — 全局模块注册表

所有模块（音频源、识别、翻译、过滤、消费者）**统一**在此以 `ref_id` 为键定义。
`ref_id` 在整个配置文件中唯一标识一个模块逻辑，pipeline 仅通过 `ref_id` 引用它。

```json
"modules": {
  "<ref_id>": {
    "type":   "<注册类型字符串>",
    "params": { "<参数>": "<值>", ... }
  }
}
```

### 支持的 type 值

| type | 类 | 说明 |
|------|----|------|
| `"microphone"` | `MicrophoneSource` | 麦克风音频源 |
| `"loopback"` | `LoopbackSource` | 系统音频环回源 |
| `"volc_streaming_stt"` | `VolcStreamingSTT` | 火山引擎流式 STT |
| `"volc_machine_translation"` | `VolcMachineTranslation` | 火山引擎机器翻译 |
| `"baidu_machine_translation"` | `BaiduMachineTranslation` | 百度通用翻译 |
| `"terminal"` | `TerminalConsumer` | 终端输出 |
| `"osc_vrchat"` | `VRChatOSCConsumer` | VRChat OSC 输出 |
| `"filter"` | `PacketFilter` | 通用包过滤器 |

### 注意事项

- `params` 中可用 `${ENV_VAR}` 引用系统环境变量（敏感 key 推荐此方式）
- engine 会自动向每个模块的 params 注入 `_ref_id`、`pipeline_id`、`pipeline_name`，**不需要**手动填写
- 同一 `ref_id` 可被多条 pipeline 引用（引擎为每条 pipeline 独立实例化）

---

## pipelines — 管道列表

```json
"pipelines": [
  {
    "id":      "唯一 pipeline ID",
    "name":    "人类可读名称",
    "enabled": true,
    "graph": {
      "entry":  "<PacketProducerModule 的 ref_id>",
      "routes": {
        "<from_ref_id>": ["<to_ref_id>", ...],
        ...
      }
    }
  }
]
```

### 规则

- `enabled: false` 的 pipeline 被 engine 跳过，不实例化任何模块
- `entry` 必须是 `PacketProducerModule` 类型模块的 `ref_id`（否则 `Pipeline.__post_init__` 报错）
- `routes` 的邻接表中出现的所有 `ref_id`（包括 entry、from、to）必须在全局 `modules` 中定义
- `routes` 中可定义 fan-out（一对多）：`"volc_stt": ["terminal_out", "final_only"]`
- `routes` 中未出现的孤立 `ref_id` 不会被连线（但仍会被实例化和启动）

### fan-out 行为

当一个模块有多个下游时：
- 每个下游收到**独立的深拷贝**（`packet.clone()`），不共享状态
- 广播顺序与 routes 列表顺序一致（但由于是多线程，处理顺序不保证）

---

## 当前配置的两条管道

### vrchat_volc_streaming（启用，流式单语）

```
loopback_vrchat → volc_stt → terminal_out   （实时流式显示，含中间结果）
                           ↘ final_only → mt_zh → osc_out
```

- `final_only` 过滤掉 `is_partial=True` 的包，只让最终识别结果进入翻译环节
- `mt_zh` 翻译成中文后发送到 VRChat 聊天框

### vrchat_bilingual（禁用，双语示例）

```
loopback_vrchat → volc_stt → mt_zh → terminal_bilingual
                           ↘ mt_ja → osc_bilingual
```

- 两路翻译（中文+日文）并行
- `terminal_bilingual` 和 `osc_bilingual` 均配置了 `group_by: "timestamp_volc_stt"`
- 同一 STT 时间戳的两个翻译结果会被合并为一行显示，格式：`中文结果 / 日文结果`

---

## gui — Web GUI 配置

```json
"gui": {
  "enabled": true,
  "host":    "0.0.0.0",
  "port":    8082
}
```

GUI 为可选功能。`enabled: false` 时不启动 Web 服务器，程序仍可正常运行，
翻译结果通过 TerminalConsumer 在命令行输出。

---

## 完整 modules 字段参考

### loopback_vrchat

```json
"loopback_vrchat": {
  "type": "loopback",
  "params": {
    "process_name": "VRChat.exe",   // null = 默认扬声器
    "sample_rate": 16000,
    "vad_mode": 3,                  // 0-3，3 最灵敏
    "mode": "streaming",            // "batch" 或 "streaming"
    "chunk_ms": 200                 // 流式模式每包时长（ms）
  }
}
```

### volc_stt

```json
"volc_stt": {
  "type": "volc_streaming_stt",
  "params": {
    "api_key": "${VOLC_API_KEY}",                  // 新版控制台 UUID Key
    "resource_id": "volc.seedasr.sauc.duration",   // 按时长计费资源
    "language": "en",
    "streaming_mode": true                          // 与音频源 mode="streaming" 配套
  }
}
```

### mt_zh / mt_ja

```json
"mt_zh": {
  "type": "volc_machine_translation",
  "params": {
    "api_key": "${VOLC_API_KEY}",
    "source_language": "",           // 空 = 自动检测
    "target_language": "zh"
  }
}
```

### terminal_out

```json
"terminal_out": {
  "type": "terminal",
  "params": {
    "color": true
  }
}
```

### osc_out

```json
"osc_out": {
  "type": "osc_vrchat",
  "params": {
    "host": "127.0.0.1",
    "port": 9000,
    "trigger_sfx": false
  }
}
```

### final_only（过滤器）

```json
"final_only": {
  "type": "filter",
  "params": {
    "field": "is_partial",   // 检查 is_partial 字段
    "pass_when": false       // 只放行 is_partial=false 的包
  }
}
```

---

## 添加新管道的步骤

1. 在 `modules` 中定义所需的模块（已有的 `ref_id` 可直接复用）
2. 在 `pipelines` 数组中追加新条目，写好 `graph.entry` 和 `graph.routes`
3. 将 `enabled` 设为 `true`
4. 重启程序（或调用 `engine.reload_config()`）

新增模块**类型**需要额外在 `core/engine.py` 的 `PRODUCER_REGISTRY` 或 `MODULE_REGISTRY` 中注册。
