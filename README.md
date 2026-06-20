# VRCTTP - VRChat 实时流式翻译工具

> 🎯 **让 VRChat 跨语言交流零障碍**  
> 实时捕获游戏或麦克风音频 → 语音识别 → 机器翻译 → OSC 发送至游戏聊天框

---

## 📥 下载与安装

### 首次使用（推荐）
👉 **https://pan.quark.cn/s/232eeac3d38b**

### 版本更新
1. 前往 **https://github.com/sanmusen214/VRCTTP/releases/** 下载最新 `exe` 文件
2. 直接替换原程序目录中的旧 `exe` 即可

### 交流反馈
💬 **QQ 交流群：964670098**  
📺 **B站视频**: **https://www.bilibili.com/video/BV1cgjN6fEfm/**

> ⚠️ 作者不常看评论区，有问题请进群咨询

---

## ✨ 核心功能

| 功能 | 说明 |
|------|------|
| 🎧 **音频捕获** | 支持 VRChat 游戏音频环回 + 系统麦克风双输入 |
| 🗣️ **语音识别** | 在线/本地语音识别模块可选 |
| 🌍 **实时翻译** | 多翻译模块可选，支持多语种并行 |
| 📺 **多端输出** | VRChat OSC 聊天框 / 终端实时显示 / GUI 面板 |
| 🔀 **多管道并行** | 同时处理多路音频流，互不干扰 |
| 🖥️ **可视化 GUI** | NiceGUI 网页管理台，配置热更新 |

---

## 🏗️ 系统架构

```
┌─────────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ LoopbackSource  │───▶│ VolcSTT     │───▶│ Translation │───▶│ VRChat OSC │
│ (游戏/麦克风音频)│    │ (流式识别)   │    │ (多语种翻译) │    │ (游戏聊天框) │
└─────────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
                                                      │
                                                      ▼
                                             ┌─────────────────────┐
                                             │   TerminalConsumer   │
                                             │   (终端/GUI 实时显示) │
                                             └─────────────────────┘
```

## 🚀 快速启动

### 方式一：直接运行（推荐）
```bash
# 双击 VRCTTP.exe 即可
# 程序自动启动 Web GUI（默认 http://localhost:8082）
```

### 方式二：命令行启动
```bash
python main.py              # 默认配置 + 启动 GUI
python main.py --no-gui     # 不启动 GUI，仅命令行运行
python main.py --list-devices  # 列出所有音频设备
```

---

## ⚙️ 配置文件（config.json）

（推荐）请前往 [百度翻译开放平台](https://fanyi-api.baidu.com/product/11) 进行注册并认证为个人开发者，随后开通 通用文本翻译 服务，并填写百度相关密钥

### 环境变量设置
```bash
# Windows PowerShell
$env:BAIDU_APP_ID="your-baidu-app-id"
$env:BAIDU_APP_KEY="your-baidu-app-key"

# 或创建 .env 文件
BAIDU_APP_ID=your-baidu-app-id
BAIDU_APP_KEY=your-baidu-app-key
```

或者请前往 [火山引擎-豆包语音](https://console.volcengine.com/speech/new/setting/apikeys?projectName=default) 注册并开通 语音识别 与 机器翻译服务，并填写相关火山引擎密钥（新版控制台）`VOLC_API_KEY`

✨ 如果你有想要使用的语音识别或翻译模块，欢迎根据 ai_documents 文档指引，进行模块的搭建，测试以及pr。 ✨

## ❓ 常见问题

**Q：VRChat 无文字发送？**  
A：确认 VRChat 已开启 OSC 功能（设置 → OSC → 启用）

---

## 📋 系统要求

- **操作系统**：Windows 10/11
- **Python**：3.10（源码开发）
- **依赖**：见 `requirements.txt`
- **硬件**：支持音频输入的设备
