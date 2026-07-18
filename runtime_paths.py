"""运行时文件路径及首次启动配置初始化。"""
from __future__ import annotations

import os
import shutil
import sys
import json

# JSON-compatible list: keep this as plain dict/list/string data so it can also
# be serialized directly for future GUI/API use.
MINIMUM_ENV_KEYS = [
    {
        "key": "VOLC_API_KEY",
        "description": "用于 火山引擎语音识别 和 火山机器翻译 模块的密钥。前往 [火山引擎豆包语音控制台](https://console.volcengine.com/speech/new/setting/activate?projectName=default) 开通【大模型-机器翻译】和【大模型-流式语音识别2.0】服务并在 [API管理页面](https://console.volcengine.com/speech/new/setting/apikeys?projectName=default) 获取 API Key。",
    },
    {
        "key": "BAIDU_APP_ID",
        "description": "百度翻译模块 所需的凭证之一。前往 [百度翻译开放平台](https://fanyi-api.baidu.com/manage/developer)完成开发者认证并开通【[通用文本翻译](https://fanyi-api.baidu.com/choose)】后，在[管理控制台](https://fanyi-api.baidu.com/manage/developer)页面上方获取 APP ID。",
    },
    {
        "key": "BAIDU_APP_KEY",
        "description": "百度翻译模块 所需的凭证之一。与 `BAIDU_APP_ID` 配套使用，可在百度翻译开放平台的同一应用中获取密钥。",
    },
    {
        "key": "llm_api_key",
        "description": "用于 语言大模型 模块的密钥。请在所选 LLM 服务商的控制台创建 API Key填入。并检查对应大语言模型请求格式是否一致。默认的请求格式是[火山豆包模型](https://console.volcengine.com/ark/region:cn-beijing/openManagement?LLM=%7B%7D&advancedActiveKey=model)的。",
    },
]


def minimum_env_key_names() -> list[str]:
    return [item["key"] for item in MINIMUM_ENV_KEYS]


def application_dir() -> str:
    """源码运行时返回项目目录，PyInstaller 运行时返回 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def env_path() -> str:
    return os.path.join(application_dir(), ".env")


def ensure_minimum_env_file(path: str | None = None) -> str:
    """创建/补齐最低字段，保留已有注释、字段和值。"""
    path = path or env_path()
    existing_keys: set[str] = set()
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                key, separator, _ = line.partition("=")
                if separator:
                    existing_keys.add(key.strip())

    missing = [key for key in minimum_env_key_names() if key not in existing_keys]
    if missing:
        needs_newline = os.path.isfile(path) and os.path.getsize(path) > 0
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            if needs_newline:
                with open(path, "rb") as current:
                    current.seek(-1, os.SEEK_END)
                    if current.read(1) not in (b"\n", b"\r"):
                        f.write("\n")
            for key in missing:
                f.write(f"{key}=\n")
    return path


def minimum_env_values(path: str | None = None) -> dict[str, str]:
    """读取最低字段在 .env 中的值；不存在的字段视为空值。"""
    values = {key: "" for key in minimum_env_key_names()}
    path = path or env_path()
    if not os.path.isfile(path):
        return values
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            key, separator, value = line.rstrip("\r\n").partition("=")
            key = key.strip()
            if separator and key in values:
                values[key] = value.strip()
    return values


def all_minimum_env_values_empty(path: str | None = None) -> bool:
    return not any(minimum_env_values(path).values())


def grouped_minimum_env_help() -> list[dict[str, str]]:
    """按 KEY 的首个下划线前缀分组，合并同组说明供提醒框展示。"""
    groups: dict[str, dict[str, list[str]]] = {}
    for item in MINIMUM_ENV_KEYS:
        prefix = item["key"].split("_", 1)[0]
        group = groups.setdefault(prefix, {"keys": [], "descriptions": []})
        group["keys"].append(item["key"])
        group["descriptions"].append(item["description"])
    return [
        {
            "keys": " / ".join(group["keys"]),
            "description": "  \n".join(group["descriptions"]),
        }
        for group in groups.values()
    ]


def default_config_path() -> str:
    """取得默认配置；首次启动时将随包模板移动为 config.json。"""
    config = os.path.join(application_dir(), "config.json")
    if not os.path.isfile(config):
        example = os.path.join(application_dir(), "tmp", "example_config.json")
        if os.path.isfile(example):
            shutil.move(example, config)
    return config


def software_config_path() -> str:
    return os.path.join(application_dir(), "settings", "software_config.json")


def sync_software_version(version: str, path: str | None = None) -> str:
    """确保软件配置存在，并把 NOWVERSION 同步为当前程序版本。"""
    path = path or software_config_path()
    config: dict = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
        except (json.JSONDecodeError, OSError):
            loaded = {}
        if isinstance(loaded, dict):
            config = loaded
    if config.get("NOWVERSION") != version:
        config["NOWVERSION"] = version
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    return path
