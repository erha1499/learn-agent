"""把跑完的任务导出成评测题候选：问题、当时每个工具的返回（评测时回放，保证每个版本看到同样的数据）、
Agent 的结论、它用的配置指纹；正确答案留空，等人标注（单元十四）。导出前先脱敏。"""
import re

REDACT = [
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "<IP>"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "<EMAIL>"),
    (re.compile(r"\b(user_id|uid)(\s*=\s*)\d+", re.I), r"\1\2<ID>"),
]


def redact(text):
    for pat, rep in REDACT:
        text = pat.sub(rep, text or "")
    return text


def to_case(job, events):
    tools, answer = {}, None
    for e in events:
        if e["type"] == "tool":
            tools.setdefault(e["payload"]["name"], []).append(redact(e["payload"]["result"]))
        elif e["type"] == "final":
            answer = e["payload"].get("answer")
    return {"source_job": job["job_id"], "config_id": job["config_id"], "question": redact(job["question"]),
            "recorded_tools": tools, "agent_answer": redact(answer)[-200:] if answer else None, "label": None}
