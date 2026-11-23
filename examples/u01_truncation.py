"""单元一 · 输出上限：让模型返回一段 JSON，但 max_tokens 给得不够，会发生什么？

    python examples/u01_truncation.py            # 真调模型（2 次）
    python examples/u01_truncation.py --replay
"""
import json

from _llm import chat, replay_or_run

PROMPT = ("列出 MySQL 连接数打满的 5 个常见原因，只输出 JSON 数组，"
          '每个元素是 {"cause": 原因, "check": 怎么确认}，不要输出别的。')


def run():
    out = {}
    for limit in (40, 800):
        r = chat([{"role": "user", "content": PROMPT}], max_tokens=limit, temperature=0)
        out[str(limit)] = {"text": r["text"], "finish_reason": r["finish_reason"], "out_tokens": r["usage"].get("completion_tokens")}
    return out


r = replay_or_run("u01_truncation", run)
for limit, x in r.items():
    if limit.startswith("_"):
        continue
    text = x["text"].strip().removeprefix("```json").removesuffix("```").strip()
    try:
        json.loads(text)
        parsed = "能解析"
    except json.JSONDecodeError as e:
        parsed = f"解析失败：{e.msg}，出错位置附近：{text[max(0, e.pos - 12):e.pos + 4]!r}"
    print(f"max_tokens={limit}：finish_reason={x['finish_reason']}，输出 {x['out_tokens']} 个 token，JSON {parsed}")
    print("  " + x["text"].replace("\n", " ")[:160] + ("…" if len(x["text"]) > 160 else ""))
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
