"""单元一 · token：同样的意思，中文、英文、JSON、日志各占多少 token？

调法：每段文字单独发一次，max_tokens=1（只让模型吐一个字，几乎不花输出费），看返回的 prompt_tokens。
同一个模板里减掉"空消息"的 prompt_tokens，剩下的就是这段文字自己占的 token。

    python examples/u01_tokens.py            # 真调模型（约 7 次，花费不到 1 分钱）
    python examples/u01_tokens.py --replay   # 看录好的结果
"""
from _llm import chat, replay_or_run

TEXTS = {
    "中文": "数据库连接数打满，应用报错 Too many connections，请帮忙看看是什么原因。",
    "英文": "The database ran out of connections and the app reports Too many connections. Please help find the cause.",
    "JSON": '{"root_cause_id": "MYSQL_MAX_CONNECTIONS", "confidence": 0.9, "evidence": ["E2", "E5"]}',
    "日志": "2026-11-21 14:05:31 [ERROR] HikariPool-1 - Connection is not available, request timed out after 30000ms.",
    "数字": "12345678901234567890",
}


def run():
    base = chat([{"role": "user", "content": ""}], max_tokens=1)["usage"]["prompt_tokens"]
    rows = []
    for name, t in TEXTS.items():
        n = chat([{"role": "user", "content": t}], max_tokens=1)["usage"]["prompt_tokens"] - base
        rows.append({"name": name, "chars": len(t), "tokens": n})
    return {"template_overhead": base, "rows": rows}


r = replay_or_run("u01_tokens", run)
print(f"空消息本身占 {r['template_overhead']} 个 token（对话模板：角色标记、分隔符）\n")
print(f"{'内容':<6}{'字符数':>6}{'token':>7}{'字符/token':>12}")
for x in r["rows"]:
    print(f"{x['name']:<6}{x['chars']:>8}{x['tokens']:>7}{x['chars'] / x['tokens']:>12.2f}")
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
