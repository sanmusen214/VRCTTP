# GUI 架构详解

本项目使用 **NiceGUI**（≥1.4.0）作为 Web UI 框架，提供多页面管理面板。入口由 `main.py` 中的 `ui.run()` 启动，`gui/` 目录采用分层多文件架构——页面、组件与全局状态彼此独立，各司其职。

---

## 目录结构

```
gui/
├── __init__.py
├── app.py                        # 薄分发层：初始化状态 + 注册所有页面路由
├── state.py                      # 全局状态（engine 引用、翻译输出缓冲区）
├── components/
│   ├── __init__.py
│   ├── nav.py                    # 共享导航栏（含主题切换）
│   └── module_form.py            # 动态参数表单（基于 ParamType）
└── pages/
    ├── __init__.py
    ├── home.py                   # /         首页：管道状态总览
    ├── output_page.py            # /output   GUI 文字输入 + 实时翻译输出
    ├── pipelines_page.py         # /pipelines 管道 CRUD（创建/删除/路由编辑）
    ├── modules_page.py           # /modules  模块实例 CRUD + 类型参考
    ├── config_page.py            # /config   原始 JSON 配置编辑器
    └── env_page.py               # /env      .env 环境变量编辑器
```

---

## 启动流程

```
main.py
  ↓ engine.load_config()          ← 快速（仅解析 JSON）
  ↓ gui.create_app(engine)         ← 初始化状态，注册所有路由
  ↓ ui.run(show=True)              ← 启动 NiceGUI HTTP 服务，自动开启浏览器
  ↓ 后台线程: engine.build_all() + engine.start_all()
                                 ← 耐时操作（本地模型加载等）不阻塞 GUI
```

GUI 在引擎初始化前就可用。首页会显示初始化状态横幅，待后台线程完成后自动消失。

`main.py` 中 `ui.run()` 必须传入 `storage_secret`，否则 `app.storage.user`（深色模式持久化）不可用：

```python
ui.run(
    title="VRChat 实时翻译流",
    storage_secret="vrcls-gui-storage-secret",
    ...
)
```

`create_app(engine)` 做三件事：
1. 调用 `gui.state.init(engine)` 存储全局引擎引用
2. 向 `modules.consumer.terminal.register_gui_callback` 注册翻译输出回调，将结果写入 `state.output_buffer`
3. 逐一导入各页面模块并调用 `register(app)` 注册 NiceGUI 路由

---

## gui/state.py — 全局状态

| 名称 | 类型 | 说明 |
|------|------|—---|
| `_engine` | `PipelineEngine \| None` | 全局唯一引擎实例，由 `init()` 设置 |
| `output_buffer` | `deque[dict]` | 翻译输出环形缓冲区，容量 200 条 |
| `output_lock` | `threading.Lock` | 保护 `output_buffer` 的线程锁 |
| `MAX_OUTPUT_LINES` | `int` | 缓冲区最大条目数（200） |
| `_engine_init_status` | `str` | Pipeline 后台初始化状态：`"initializing"` \| `"ready"` \| `"error"` |
| `_engine_init_error` | `str` | 当 status=error 时存储错误信息 |

**API：**

```python
gui.state.init(engine)                    # 初始化，只调用一次
gui.state.get_engine()                    # 获取引擎；未初始化时抛 RuntimeError
gui.state.set_engine_ready()              # 后台初始化线程成功后调用
gui.state.set_engine_error(msg)           # 后台初始化失败时调用
gui.state.get_engine_init_status()        # 返回 (status, error_msg) 元组
```

每条 `output_buffer` 记录的格式：

```python
{
    "pipeline":   str,   # 管道名称（由 TerminalConsumer 传入）
    "original":   str,   # 识别原文
    "translated": str,   # 翻译结果
}
```

---

## gui/components/nav.py — 导航栏

每个页面在顶部调用 `create_nav()` 渲染共享导航栏。

**导航项：**

| 显示文字 | 路由 |
|----------|------|
| 首页 | `/` |
| 文字输入与输出 | `/output` |
| 管道管理 | `/pipelines` |
| 模块目录 | `/modules` |
| 配置编辑 | `/config` |
| 环境变量 | `/env` |

**深色/浅色主题切换机制：**

- 导航栏右侧有"深色"开关（`ui.switch`）
- 切换时调用 `ui.dark_mode().enable()` / `.disable()` 立即生效
- 偏好持久化到 `app.storage.user["dark_mode"]`（布尔值）
- 每次页面加载时从 `app.storage.user` 恢复上次偏好

> `app.storage.user` 需要 `ui.run(storage_secret=...)` 才能激活；未配置时读写会静默失败。

---

## gui/components/module_form.py — 动态参数表单

根据任意模块类的 `get_config_attributes()` 返回值动态生成对应的 NiceGUI 输入组件。

### create_module_form(config_attrs, current_params) → elements

| 参数 | 类型 | 说明 |
|------|------|------|
| `config_attrs` | `list[dict]` | 来自 `get_config_attributes()` 的 schema |
| `current_params` | `dict` | 当前 config 中已存的参数值（用于回填） |
| 返回 | `dict[str, tuple[ui_elem, ParamType]]` | 参数名 → (UI 控件, 参数类型) |

**ParamType → NiceGUI 组件映射：**

| ParamType | NiceGUI 组件 |
|-----------|-------------|
| `String` | `ui.input` |
| `Int` | `ui.input(type=number)` |
| `Float` | `ui.input(type=number)` |
| `Bool` | `ui.switch` |
| `Password` | `ui.input(password=True, toggle_button=True)` |
| `Select` | `ui.select(selectable)` |
| `DirPath` | `ui.input` |
| `FilePath` | `ui.input` |
| `List` | `ui.input`（JSON 数组字符串） |
| `LanguageCode` | `ui.input` |

**动态选项加载器（options_loader）**

模块的 `get_config_attributes()` 可为某个属性添加 `"options_loader": "<loader_name>"` 字段。
`create_module_form` 检测到该字段后，会在渲染时调用对应加载器，并生成 `ui.select` 下拉菜单（能选中 None 表示系统默认）。

| 加载器名 | 来源 | 说明 |
|----------|------|—---|
| `"microphone"` | `MicrophoneSource.device_name` | 枚举当前系统所有麦克风（含“系统默认”选项） |

### read_form_values(elements) → dict

从 `create_module_form` 返回的 `elements` 中读取当前值，并转换为 Python 原生类型：

| ParamType | 转换规则 |
|-----------|---------|
| `Bool` | `bool(val)` |
| `Int` | `int(val)`，空字符串→ `None` |
| `Float` | `float(val)`，空字符串→ `None` |
| `List` | `json.loads(val)`，空→ `[]` |
| 其他 | 原始字符串，空→ `None` |

`MicrophoneSource` 与 `LoopbackSource` 的 schema 均声明了布尔参数 `sync_vrc_mic`，因此模块新建/编辑对话框会自动显示开关，并提示该选项需要启用 VRChat OSC；无需在页面代码中单独维护控件。

---

## 页面详解

### `/` — 首页（home.py）

管道状态总览，显示配置中所有管道（不限于运行中的）。

**页面顶部初始化状态横幅：**
- `_engine_init_status == "initializing"`：显示蓝色转圈 + 提示文字
- `_engine_init_status == "error"`：显示红色错误信息
- `_engine_init_status == "ready"`：横幅自动消失
- 若任一 `enabled=true` 管道实际引用了 `sync_vrc_mic=true` 的 `microphone`/`loopback` 模块：首页持续显示橙色提醒，要求翻译启动后在 VRChat 内切换一次麦克风开关以同步初始状态；同步前默认按静音处理。提醒中列出相关管道显示名称

**每个管道卡片包含：**
- 状态徽章（`running` / `enabled-pending` / `stopped`）
- 管道 ID 和名称
- `enabled` 开关

**enabled 切换流程：**

```
用户切换开关
   ↓ engine.get_raw_config() 获取当前配置
   ↓ 找到对应管道并修改 "enabled" 字段
   ↓ engine.save_config(new_raw)     「仅持久化，不重载」
   ↓ 页面刷新（await refresh()）
```

> 开关仅保存 config，不触发重载。需点击「重载所有配置」按鈕才能使改动对运行中的管道生效。

- 5 秒自动刷新（`ui.timer(5.0, refresh)`）
- 页面加载时也会立即调用一次 `refresh()`

---

### `/output` — 文字输入与实时翻译输出（output_page.py）

页面上方显示所有当前活跃的 `TextInput` 模块实例，每个实例对应一个输入框；
页面剩余空间显示 `state.output_buffer` 中最新至多 200 条翻译记录，最新条目在上。

**文字输入区：**
- 从 `TextInput._instances` 动态扫描正在运行的注入节点
- 支持按 Enter 或点击「发送」提交文字
- 提交后清空输入框，文字进入对应模块的线程安全队列
- 「刷新实例」按钮用于响应运行时模块变化

**每条记录显示：**
- 所属管道名称
- 识别原文
- 翻译结果

- 1 秒自动刷新（`ui.timer(1.0, refresh)`）
- 使用 `state.output_lock` 线程安全读取缓冲区快照

---

### `/pipelines` — 管道管理（pipelines_page.py）

该页面同时支持查看、创建与删除管道。

**每个管道卡片包含：**
- `enabled` 开关：仅保存 config（不重载）
- 路由图（模块显示名称 → 目标模块显示名称列表；内部 `ref_id` 不展示）
- **编辑** 按鈕（✏ 图标）：打开 `_open_edit_dialog()`，预填当前管道所有字段
- **复制** 按钮：深拷贝管道配置；新 ID 使用 `<原ID>_copy`，冲突时追加数字；名称使用 `<原名称>（副本）`，冲突时追加数字
- **删除** 按鈕：弹出确认对话框，确认后从 `config["pipelines"]` 中移除并保存（不重载）

**编辑管道对话框（`_open_edit_dialog(pipeline_id, pipeline_cfg)`）：**
- 管道 ID 作为只读标签显示，不可修改
- 显示名称：可修改，预填当前 `name`
- 启用开关：预填当前 `enabled` 状态
- Entry 下拉：仅列出 `PRODUCER_REGISTRY` 类型，以 `display_name` 展示并以内部 `ref_id` 保存
- 路由编辑器（`@ui.refreshable`）：从 `graph.routes` dict 转换为逐行展示，支持增删行、修改 from/to；与新建对话框结构相同
- 确认保存：按 ID 找到原管道在 list 中的位置，原地替换 `name`/`enabled`/`graph`，save（不重载）

**`_open_edit_dialog` 数据流：**
```
读取 pipeline_cfg["graph"]["routes"] dict
  ↓ 转换为 edit_routes_rows: list[{"from_ref": str, "to_refs": list[str]}]
  ↓ @ui.refreshable edit_routes_editor() 渲染各行
用户修改并点击「保存更改」
  ↓ edit_routes_rows → built_routes dict
  ↓ engine.get_raw_config() → 遍历 pipelines list → 按 id 匹配 → 原地更新
  ↓ engine.save_config()                     「仅持久化，不重载」
  ↓ edit_dlg.close() → draw_pipelines() 刷新列表
```

**新建管道对话框（`_open_create_dialog()`）：**
- 输入字段：管道 ID（唯一，不含空格）、名称、是否启用
- Entry 下拉：仅列出 `PRODUCER_REGISTRY` 中注册的模块类型（音频源）
- 路由编辑器（`@ui.refreshable`）：每行一条路由，含：
  - `from`：模块显示名称下拉（值仍为内部 `ref_id`）
  - `to`：目标模块显示名称列表（多选，值仍为内部 `ref_id`）
  - 删除按钮
- "添加路由行" 按钮动态扩展路由列表
- 确认时校验 ID 非空且不重复，构建管道 dict，追加至 `config["pipelines"]`，save（不重载）

> **重载说明**：管道页的所有写操作（创建/编辑/删除/enabled 切换）均仅保存 config 文件，不触发运行时重载。需要返回首页点击「重载所有配置」按鈕才能对正在运行的管道生效。

---

### `/modules` — 模块实例管理（modules_page.py）

该页面分三个区块：

#### 区块 A — 现有实例列表（可刷新）

`draw_instances()` 使用 `@ui.refreshable` 装饰，调用 `engine.get_raw_config()` 读取 `config["modules"]`（跳过 `_` 前缀内部键）。

每个实例以 `ui.expansion` 展示：
- 标题仅显示 `display_name` 和模块类型，不显示内部 `ref_id`
- 当前 params 键值
- **编辑** 按钮：可修改 `display_name` 和参数。改名只更新显示名称，内部 `ref_id` 与所有管道路由不变
- **复制** 按钮：深拷贝模块类型和参数；生成唯一的 `<原显示名称>（副本）`，再由该名称生成新的哈希 `ref_id`
- **删除此实例** 按钮：弹出确认对话框；若该 ref_id 被任意管道 routes 引用，则显示橙色警告（仍可删除）；确认后从 config 中移除并 `engine.save_config()`（**不自动重载**）

#### 区块 B — 新增模块实例

| 控件 | 说明 |
|------|------|
| 显示名称输入框 | GUI 名称（不能为空、不能与已有模块重名） |
| 模块类型下拉 | 来自 `engine.get_module_classes()`（字母序） |
| 动态参数表单 | 随类型切换实时重建（`on_change=lambda e: _rebuild_form(e.value)`） |

类型切换通过 `ui.select` 的 `on_change` kwarg 绑定，`e.value` 提取新值（避免 `.on("update:model-value", ...)` 的 `e.args` 返回 Vue 原始 dict 的问题）。

确认创建流程：
```
display_name 非空校验 → 显示名称无重名校验
  ↓ `module_ref_id(display_name)` 生成不可见的稳定哈希 ID
  ↓ read_form_values(form_elements)
  ↓ 过滤 None 值
  ↓ engine.get_raw_config()["modules"][ref_id] = {"display_name": ..., "type": ..., "params": ...}
  ↓ engine.save_config()         # 仅持久化，不 reload
  ↓ ui.notify()
  ↓ draw_instances()             # 刷新实例列表
```

#### 区块 C — 模块类型参考（只读，默认折叠）

`ui.expansion("模块类型参考（只读）", value=False)` 内，对每个已注册类型渲染三张元信息表格：require_attributes、add_attributes、config_attributes。直接消费类方法，无需手写文档即可自动生成契约视图。

#### 模块身份兼容规则

- 新建/复制模块：生成 `mod_<16位SHA-256摘要>` 作为内部 `ref_id`
- 修改显示名称：只修改 `display_name`，不重新计算 `ref_id`
- 旧配置：加载时以内存规范化方式用原键补齐 `display_name`，下次保存时持久化；原路由和共享实例缓存完全不变
- 管道页、模块页、文字输入区和本地模型告警均只显示 `display_name`

---

### `/env` — 环境变量编辑（env_page.py）

读写项目根目录下的 `.env` 文件，保留注释和空行。

**`_read_env_file(path)`：**
- 返回 `(header_lines: list[str], kv_pairs: list[tuple[str,str]])`
- 注释行（`#`）和空行归入 `header_lines`（原样保留）
- `KEY=VALUE` 行解析为 `(key, value)` tuple

**`_write_env_file(path, header_lines, kv_pairs)`：**
- 先写入所有 header_lines，再写入 KV 对（`KEY=VALUE\n` 格式）

**敏感键检测（`_is_sensitive(key)`）：**
- key 小写名称包含 `key / secret / token / password / pass / pwd` 之一 → 使用密码框显示

**UI 布局：**
- 每个 KV 对渲染一行：键标签（只读）+ 值输入框（敏感时密码框）+ 删除按钮
- 底部有"添加新变量"行：键名输入 + 值输入 + 添加按钮
- "保存到 .env" 按钮将内存中 `kv_list` 写回文件
- 提示：修改 `.env` 后需重启应用才能生效

---

### `/config` — 原始配置编辑（config_page.py）

提供原始 `config.json` 的 JSON 文本编辑器（`ui.textarea`，32 行，等宽字体）。

**两个操作按钮：**

| 按钮 | 行为 |
|------|------|
| 保存 | `json.loads(text)` → `engine.save_config(parsed)` |
| 保存并重载 | 保存 + `engine.reload_config()` |

保存前会 JSON 解析校验，解析失败时弹出错误通知（不写入文件）。

---

## 数据流总览

```
音频源（Producer）
    ↓ [音频 Packet]
STT 模块
    ↓ [含 text_original 的 Packet]
翻译模块
    ↓ [含 text_translated 的 Packet]
TerminalConsumer
    ├→ 终端彩色打印
    └→ register_gui_callback → state.output_buffer
                                    ↓
                            /output 页面下半部分定时读取并渲染
```

`engine.get_status()` 和 `engine.get_raw_config()` 供所有管道相关页面（`/`, `/pipelines`, `/config`）查询当前状态与配置。

---

## 主题切换数据流

```
用户切换开关（nav.py）
    ↓ ui.dark_mode().enable/disable()  立即生效
    ↓ app.storage.user["dark_mode"] = True/False  持久化
    
页面加载（任意页面）
    ↓ create_nav() 读取 app.storage.user.get("dark_mode")
    ↓ 恢复上次主题偏好
```
