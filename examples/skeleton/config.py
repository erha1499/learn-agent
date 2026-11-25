"""配置：所有会改变输出的东西放在一处，算一个指纹（config_id），每个任务、每条事件都带上它。

只影响快慢、不影响输出的运维参数（并发、超时、重试）单独放，不进指纹：改它们不该让评测结果“换了一个版本”。
"""
import hashlib
import json

from mini_eval import SYSTEM, TOOLS


def behavior_config():
    return {
        "agent": "oncall",
        "model": "qwen-plus",
        "params": {},                                   # temperature 等；空表示用服务端默认值
        "system_prompt": SYSTEM,                        # 提示词原文，不是“v3”这样的标签
        "tools": TOOLS,                                 # 工具定义原文：描述改一个字，行为就可能变
        "limits": {"max_turns": 10, "max_tokens_per_job": 30000},
        "grader": "verdict-strict-v1",
    }


def ops_config():
    return {"workers": 4, "gateway_concurrency": 4, "max_retries": 4, "lease_s": 8}


def config_id(cfg):
    body = json.dumps(cfg, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()[:12]
