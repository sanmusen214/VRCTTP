# 实时翻译流 — 项目总体概览

## 目标

将 VRChat（或任意应用）的音频实时识别、翻译，并把结果推送到 VRChat 聊天框（通过 OSC 协议），或打印到终端。典型场景：英文→中文实时字幕。

---

## 顶层文件结构

```
实时翻译流/
├── main.py              # 入口：CLI 参数解析、引擎启动、信号处理
├── config.json          # 运行配置（模块注册 + 管道拓扑）
├── requirements.txt     # Python 依赖
├── validate_volc_stt.py # 独立验证：火山引擎 STT 连通性测试
├── validate_volc_mt.py  # 独立验证：火山引擎 MT 连通性测试
├── core/                # 框架核心（不含业务逻辑）
├── modules/             # 业务模块（音频、翻译、过滤、消费）
├── gui/                 # Web GUI（可选）
└── ai_document/         # 本文档目录
```

---

## 整体架构：有向无环图（DAG）管道

系统以 **MessagePacket** 为信息流通单元，沿着用户在 `config.json` 中描述的 DAG 拓扑流动。

```
PacketProducerModule          PacketConsumerModule（可多级串联、分叉）
─────────────────┐
 LoopbackSource  │──▶ VolcStreamingSTT ──▶ PacketFilter(final_only) ──▶ VolcMachineTranslation ──▶ VRChatOSCConsumer
 MicrophoneSource│                    ╰──▶ TerminalConsumer（实时流式显示）
─────────────────┘
```

每个节点运行在独立的后台守护线程中，节点之间通过 `queue.Queue`（容量 200）传递包的引用（单下游）或深度克隆（多下游 fan-out）。

---

## 核心概念速览

| 概念 | 说明 |
|------|------|
| `MessagePacket` | 在管道中流动的数据包，带 `data` 字典和 `is_partial` 属性 |
| `PacketProducerModule` | 主动产包，是管道的**根节点**（如音频源） |
| `PacketConsumerModule` | 从队列取包处理，是管道的**中间/叶节点** |
| `Pipeline` | 一组模块 + 路由描述（邻接表），对应一条翻译任务 |
| `PipelineEngine` | 加载配置、实例化所有模块、统一管理生命周期 |
| `PacketFilter` | 通用过滤节点，根据包字段值决定是否放行 |

---

## 典型数据流（流式模式）

```
1. LoopbackSource（捕获 VRChat 音频，VAD 分段）
      │ is_partial=True  ← 语音段进行中，每 200ms 一个 chunk
      │ is_partial=False ← 语音段结束
      ▼
2. VolcStreamingSTT（WebSocket 流式 STT）
      │ is_partial=True  ← 中间识别文字（边说边出）
      │ is_partial=False ← 最终识别文字
      ├──▶ TerminalConsumer（实时显示所有结果，不等翻译）
      └──▶ PacketFilter "final_only"（丢弃 is_partial=True 包）
                │ is_partial=False only
                ▼
3. VolcMachineTranslation（HTTP 翻译 API）
      │ is_partial=False（翻译结果填入 text_translated）
      ▼
4. VRChatOSCConsumer（OSC /chatbox/input → VRChat 聊天框）
```

---

## 入口（main.py）

```bash
python main.py                        # 默认配置，启动 GUI
python main.py --config custom.json   # 指定配置文件
python main.py --no-gui               # 不启动 Web GUI
python main.py --list-devices         # 列出音频设备后退出
```

启动流程：
1. 解析 CLI 参数
2. `PipelineEngine.load_config()` → 解析 config.json + 环境变量替换
3. `PipelineEngine.build_all()` → 实例化模块 + 按路由连线
4. `PipelineEngine.start_all()` → 按拓扑序启动所有线程
5. 注册 `SIGINT/SIGTERM` → 触发 `stop_all()`（按反拓扑序停止）

---

## 依赖说明

| 包 | 用途 |
|----|------|
| `soundcard` | 跨平台音频捕获（麦克风 / WASAPI 环回） |
| `webrtcvad` | 语音活动检测（VAD） |
| `numpy` | 音频数据处理 |
| `aiohttp` | 火山引擎 STT WebSocket 客户端 |
| `requests` | 火山引擎 MT HTTP 客户端 |
| `python-osc` | OSC 协议发送（VRChat chatbox） |
| `colorama` | 终端彩色输出（可选） |
| `scipy` | 高质量音频重采样（可选，退路用 numpy） |

---

## 环境变量

| 变量名 | 说明 |
|--------|------|
| `VOLC_API_KEY` | 火山引擎新版控制台 API Key（UUID 格式），由 config.json 中 `${VOLC_API_KEY}` 引用 |

旧版控制台改用 `app_id` + `access_key` 直接写入 config.json params（或通过其他环境变量引用）。
