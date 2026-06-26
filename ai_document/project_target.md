# 项目目标与需求整理

本文保留项目的原始目标，并整理成当前架构下的需求说明。

## 总目标

实现一个面向 VRChat 的实时翻译工具：

1. 从 VRChat、系统声音或麦克风采集音频。
2. 将音频识别成文字。
3. 将文字翻译成一个或多个目标语言。
4. 将结果输出到终端、GUI 或 VRChat 聊天框。

项目只需要优先保证 Windows 平台可用。

## 核心设计思想

系统采用管道和模块化设计。每个处理环节都是一个模块，每条 pipeline 定义模块之间的连接关系。

```text
输入模块 -> 识别模块 -> 翻译模块 -> 输出模块
```

同一个包可以被 fan-out 给多个下游模块，因此支持：

- 同一段语音同时显示原文和译文。
- 同一段文字并行翻译为多种语言。
- 同一个输出消费者合并多路翻译结果。

## 信息包模型

每条音频、识别文本或翻译结果都封装在 `MessagePacket` 中。模块不直接共享全局状态，而是通过给包添加字段来传递信息。

示例：

```text
音频源写入 audio_data
STT 写入 text_original
翻译模块写入 text_translated 和 target_lang
输出模块读取 text_original / text_translated
```

## 音频输入需求

音频输入模块应支持：

- 麦克风采集。
- VRChat 或系统音频 loopback。
- VAD 分段。
- 批处理模式和流式模式。
- 多线程运行，避免采集被下游 API 阻塞。
- 可选跟随 VRChat 游戏内麦克风状态。

## 翻译链路需求

项目需要支持多种翻译链路：

1. 云端流式 STT。
2. 本地 STT。
3. 传统机器翻译 API。
4. 通用 LLM API 翻译。

对于语音输入，常见链路是：

```text
音频 -> STT -> text_original -> 翻译 -> text_translated
```

对于 GUI 手动输入，可跳过音频和 STT：

```text
TextInput -> 翻译 -> 输出
```

## 输出需求

输出模块至少支持：

- 终端打印。
- GUI 输出列表。
- VRChat OSC chatbox。

输出模块应能读取：

- `text_original`
- `text_translated`
- `source_lang`
- `target_lang`

并允许通过模板控制最终显示内容。

## 配置需求

配置文件应满足：

- 定义所有模块实例。
- 定义所有 pipeline。
- 支持多个 pipeline 同时运行。
- 支持模块复用。
- 支持环境变量引用敏感信息。
- 可由 GUI 编辑。

当前实现使用 `config.json`，并以 `modules` + `pipelines[].graph` 描述 DAG。

## GUI 需求

GUI 应提供：

- 管道启用/禁用。
- 配置保存和热重载。
- 模块增删改查。
- 管道路由编辑。
- 文本输入。
- 实时输出查看。
- `.env` 环境变量编辑。

GUI 不应成为核心功能的必需条件；禁用 GUI 后，管道仍应能正常运行。

## 参考资源

`refer_resources/` 中保存参考代码和验证脚本。实现新模块时可以参考其 API 调用流程，但生产模块应遵循本项目的 `MessagePacket`、模块基类和配置约定。
