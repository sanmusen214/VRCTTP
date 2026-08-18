"""模块运行时策略声明与匹配逻辑。"""

from __future__ import annotations

from typing import Any


# 匹配模块类型和用户参数后，由通用逻辑注入隐式配置。
# 新增同类策略只需添加声明，无需修改 Pipeline 构建流程。
MODULE_RUNTIME_POLICY_RULES: tuple[dict[str, Any], ...] = (
    {
        "module_type": "local_stt",
        "when": {"streaming_mode": True},
        "inject": {
            "_queue_policy": "coalesce_streaming_audio",
            "_queue_options": {"warning_seconds": 3.0},
        },
    },
)


def apply_module_runtime_policies(module_type: str, params: dict[str, Any]) -> None:
    """将匹配的声明式运行策略注入模块参数。"""
    for rule in MODULE_RUNTIME_POLICY_RULES:
        if rule["module_type"] != module_type:
            continue
        if not all(params.get(key) == value for key, value in rule["when"].items()):
            continue
        for key, value in rule["inject"].items():
            params[key] = value.copy() if isinstance(value, dict) else value
