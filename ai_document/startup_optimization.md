# 打包版启动加载优化

## 问题现象

打包版启动后先输出 `[dotenv] 已加载`，随后长时间无 GUI。该日志之后，
`main.py` 会在创建 NiceGUI 前导入 `core.engine`。引擎注册本地 STT 模块时，
`LocalSTTModel.py` 又在文件顶层导入 FunASR 后处理工具。

FunASR 的包初始化会连带加载 `torch` 和 `modelscope`。在打包所用的 `vrctl`
环境中，优化前单独导入该后处理模块约需 11.14 秒，导入 `core.engine`
约需 9.06 秒，而导入 `gui.app` 约需 0.03 秒。因此主要瓶颈是 GUI 之前的
重型依赖导入，不是 dotenv 文件读取或 NiceGUI 本身。

## 变更

- 移除 `LocalSTTModel.py` 顶层的 `rich_transcription_postprocess` 导入。
- 仅在批处理本地 STT 实际执行 `_infer_full()` 时导入后处理函数。
- `AutoModel` 仍由 `on_start()` 加载；该方法在 GUI 启动后的 Pipeline 后台初始化
  线程中执行。
- PyInstaller 的 FunASR 收集配置保持不变，发布包仍包含本地 STT 所需依赖。

## 行为边界

本次变更只调整导入时机，不改变模块注册、配置解析、模型加载、
推理参数和文本后处理逻辑。启用 `local_stt` 时仍会完整加载 FunASR；区别是
该工作不再发生于 GUI 创建前的主线程导入阶段。

`tests/test_startup_imports.py` 使用独立 Python 进程导入本地 STT 模块，并验证此时
`sys.modules` 中不存在 `funasr` 和 `torch`，防止后续修改重新引入启动回归。
