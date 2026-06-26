# GUI 架构说明

项目使用 NiceGUI 提供 Web 管理界面。GUI 负责配置管理、管道启停状态查看、模块编辑、文本输入和翻译结果展示。

```text
gui/
├── app.py                  # 初始化 GUI 状态并注册页面
├── state.py                # 全局 engine 引用和输出缓冲
├── components/
│   ├── nav.py              # 顶部导航和主题切换
│   └── module_form.py      # 动态模块参数表单
└── pages/
    ├── home.py             # 首页
    ├── output_page.py      # 文本输入与输出
    ├── pipelines_page.py   # 管道管理
    ├── modules_page.py     # 模块管理
    ├── config_page.py      # 原始 JSON 编辑
    └── env_page.py         # .env 编辑
```

## 启动流程

1. `main.py` 创建 `PipelineEngine` 并加载配置。
2. `gui.create_app(engine)` 保存全局 engine 引用。
3. GUI 注册 `TerminalConsumer` 回调，用于将输出写入 `state.output_buffer`。
4. NiceGUI 启动 Web 服务。
5. 后台线程构建并启动管道，不阻塞页面打开。

`ui.run()` 需要 `storage_secret`，否则用户级 storage 不能保存深色模式偏好。

## 全局状态

`gui/state.py` 维护：

| 名称 | 说明 |
|------|------|
| `_engine` | 全局 `PipelineEngine` |
| `output_buffer` | 最近翻译输出，最多 200 条 |
| `output_lock` | 输出缓冲线程锁 |
| `_engine_init_status` | `initializing` / `ready` / `error` |
| `_engine_init_error` | 初始化错误信息 |

输出记录结构：

```python
{
    "pipeline": "管道名称",
    "original": "原文",
    "translated": "译文",
}
```

## 导航栏

所有页面顶部都调用 `create_nav()`。

| 页面 | 路由 |
|------|------|
| 首页 | `/` |
| 文字输入与输出 | `/output` |
| 管道管理 | `/pipelines` |
| 模块目录 | `/modules` |
| 配置编辑 | `/config` |
| 环境变量 | `/env` |

导航栏提供深色模式开关，状态保存到 `app.storage.user["dark_mode"]`。

## 首页

路由：`/`

功能：

- 显示 engine 初始化状态。
- 显示所有 pipeline 的启用状态和运行状态。
- 切换 pipeline 的 `enabled` 字段。
- 提供“重载所有配置”操作。
- 当启用的 pipeline 使用 `sync_vrc_mic=true` 时，显示 VRChat OSC 同步提醒。

注意：切换 `enabled` 只保存配置，不会立即重载运行中的管道。

## 文字输入与输出

路由：`/output`

功能：

- 扫描当前运行的 `TextInput` 实例。
- 为每个实例提供输入框。
- 用户提交文本后进入对应 `TextInput` 队列。
- 定时读取 `state.output_buffer`，显示最新翻译结果。

适合调试翻译模块，也适合在没有音频输入时手动发送文本。

## 管道管理

路由：`/pipelines`

功能：

- 查看所有 pipeline。
- 创建、编辑、复制、删除 pipeline。
- 修改 `enabled`。
- 使用显示名称编辑路由，但保存内部 `ref_id`。
- 入口模块和路由表下拉菜单按管道流向分组显示：输入源、语音识别、过滤处理、翻译、输出、其他。

路由编辑器使用行式结构：

| 字段 | 说明 |
|------|------|
| `from` | 上游模块 |
| `to` | 一个或多个下游模块 |

所有写操作只保存配置，不自动重载运行时。

## 模块管理

路由：`/modules`

功能：

- 查看现有模块实例。
- 编辑模块 `display_name` 和参数。
- 复制模块。
- 删除模块。
- 创建新模块。
- 查看模块类型参考表。

模块实例、模块类型选择和模块类型参考表按管道流向分区展示，添加新的模块后需要在 gui/module_catalog 里注册该模块的分区：

| 分区 | 包含模块 |
|------|----------|
| 输入源 | `microphone`、`loopback`、`text_input` |
| 语音识别 | `volc_streaming_stt`、`local_stt` |
| 过滤处理 | `filter` |
| 翻译 | `volc_machine_translation`、`baidu_machine_translation`、`llm_openai_api_call` |
| 输出 | `terminal`、`osc_vrchat` |
| 其他 | 未显式归类的新模块类型 |

模块创建规则：

- 用户输入 `display_name`。
- GUI 生成稳定 `ref_id`。
- 保存 `{display_name, type, params}`。
- 后续改名只改 `display_name`，不改 `ref_id`。

## 动态模块表单

`gui/components/module_form.py` 根据模块类的 `get_config_attributes()` 自动生成控件。

| ParamType | GUI 控件 |
|-----------|----------|
| `String` / `LanguageCode` | `ui.input` |
| `Int` / `Float` | 数值输入 |
| `Bool` | `ui.switch` |
| `Password` | 密码输入框 |
| `Select` | 下拉选择 |
| `List` | JSON 数组输入 |
| `HeaderPairsB64` | 动态 header 键值对编辑器 |
| `JsonTextB64` | 多行 JSON 文本框 |

### HeaderPairsB64

用于 `llm_openai_api_call.headers_b64`。

行为：

- GUI 显示明文 header 键值对。
- 支持添加和删除行。
- 保存时序列化为 JSON object。
- 再编码为 base64 写入 `config.json`。

### JsonTextB64

用于 `llm_openai_api_call.payload_b64`。

行为：

- GUI 显示明文 JSON 文本。
- 输入时做基础 JSON 解析检查。
- 保存时将文本 base64 编码。
- JSON 格式可疑时给出 warning，但仍保留用户输入。

## 原始配置编辑

路由：`/config`

提供 `config.json` 的原始 JSON 文本编辑器。

按钮：

| 按钮 | 行为 |
|------|------|
| 保存 | JSON 校验后写回配置 |
| 保存并重载 | 保存后调用 `engine.reload_config()` |

## 环境变量编辑

路由：`/env`

读写项目根目录 `.env` 文件：

- 保留注释和空行。
- 敏感键使用密码输入框。
- 支持添加和删除变量。
- 保存后立即同步到当前进程的 `os.environ`，并调用 `engine.reload_config()` 热重载管道，使 `${VAR}` 配置占位符无需重启应用即可生效。

删除变量时，GUI 只会移除当前进程中仍等于旧 `.env` 值的变量，避免误删外部系统环境变量。

## 输出集成

`TerminalConsumer` 调用 GUI callback 后，数据进入 `state.output_buffer`。因此 `/output` 页面展示的是终端消费者收到的结果，而不是直接监听所有模块。

如果某条管道没有连接到 `terminal`，GUI 输出页可能看不到该管道的翻译结果。
