# 实时翻译流项目总览

本文是 `ai_document/` 的入口，帮助读者快速理解项目目标、运行方式和文档结构。

## 项目目标

本项目用于从 VRChat、系统音频或麦克风中采集语音，经过语音识别和翻译后，将结果输出到终端、GUI 或 VRChat 聊天框。系统以可配置的 DAG 管道组织模块，因此同一程序可以同时运行多条输入、识别、翻译和输出链路。

典型用途：

- 捕获 VRChat 游戏音频，识别并翻译后显示字幕。
- 捕获麦克风语音，翻译后通过 OSC 发送到 VRChat 聊天框。
- 使用 GUI 手动输入文字，走同一套翻译和输出管道。
- 扇出同一份识别结果，分别翻译成多种语言并合并输出。

## 代码结构

```text
vrc_realtime_translate/
├── main.py              # 程序入口，解析 CLI，启动 GUI 和管道引擎
├── config.json          # 运行配置：模块注册表 + 管道路由
├── core/                # 框架核心：包、模块基类、管道、引擎
├── modules/             # 业务模块：音频、输入、识别/翻译、过滤、消费
├── gui/                 # NiceGUI Web 管理界面
├── refer_resources/     # 参考代码和验证脚本
├── tests/               # 自动化测试
└── ai_document/         # 项目文档
```

## 运行入口

```bash
python main.py                        # 使用 config.json，启动 GUI
python main.py --config custom.json   # 指定配置文件
python main.py --no-gui               # 不启动 Web GUI
python main.py --list-devices         # 列出音频设备后退出
```

启动流程：

1. 加载并解析配置。
2. 创建 GUI 应用并注册页面。
3. 后台构建并启动所有启用的 pipeline。
4. 每个模块在独立后台线程中处理自己的输入队列。
5. 退出时按反拓扑顺序停止管道并释放资源。

## 数据流模型

系统使用 `MessagePacket` 作为最小数据单元。包在生产者模块中生成，并沿着 `config.json` 中定义的路由图流动。

```text
AudioSource / TextInput
  -> STT 模块
  -> PacketFilter(final_only)
  -> 翻译模块
  -> Terminal / GUI / VRChat OSC
```

一个更具体的流式管道：

```text
LoopbackSource
  -> VolcStreamingSTT
  -> PacketFilter(final_only)
  -> BaiduMachineTranslation / VolcMachineTranslation / LLMOpenAIAPICall
  -> TerminalConsumer
  -> VRChatOSCConsumer
```

同一节点可以有多个下游。框架会对多下游包进行克隆，使不同分支互不污染。

## 核心概念

| 概念 | 说明 |
|------|------|
| `MessagePacket` | 管道中传递的数据包，内部用 `data` 字典保存字段 |
| `PacketProducerModule` | 主动产包模块，例如音频源和 `TextInput` |
| `PacketConsumerModule` | 从队列取包并处理的模块，例如 STT、翻译、过滤、输出 |
| `Pipeline` | 一条启用的 DAG 管道，包含模块实例和路由图 |
| `PipelineEngine` | 加载配置、实例化模块、构建管道、统一管理生命周期 |
| `ref_id` | 配置内部使用的稳定模块 ID，参与路由和时间戳 |
| `display_name` | GUI 显示名称，可改名，不影响路由 |

## 支持的模块类别

| 类别 | 模块 |
|------|------|
| 音频源 | `microphone`, `loopback` |
| 文本输入 | `text_input` |
| 语音识别 | `volc_streaming_stt`, `local_stt` |
| 翻译 | `volc_machine_translation`, `baidu_machine_translation`, `llm_openai_api_call` |
| 过滤 | `filter` |
| 输出 | `terminal`, `osc_vrchat` |

## 文档导航

| 文档 | 内容 |
|------|------|
| `overview.md` | 项目总览、数据流和文档地图 |
| `core.md` | 核心框架：包、模块基类、管道、引擎 |
| `modules.md` | 各业务模块的功能、输入输出和配置 |
| `config.md` | `config.json` 的结构、字段、示例和环境变量 |
| `gui.md` | Web GUI 页面、表单组件和交互行为 |
| `caveats.md` | 开发约定、运行注意事项和扩展指南 |
| `project_target.md` | 原始项目目标和需求整理 |

## 常用环境变量

| 变量名 | 用途 |
|--------|------|
| `VOLC_API_KEY` | 火山引擎新版控制台 API Key |
| `BAIDU_APP_ID` | 百度翻译 APP ID |
| `BAIDU_APP_KEY` | 百度翻译密钥 |
| `llm_api_key` | `llm_openai_api_call` 默认 header 使用的 LLM API Key |

更多配置细节见 `config.md`。
