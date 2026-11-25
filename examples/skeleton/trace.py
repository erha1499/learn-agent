"""从事件日志生成一条轨迹。命名用 OpenTelemetry 的生成式 AI 语义约定（截至 2026 年 11 月仍是 Development 状态）：
一次运行是 invoke_agent，每次模型调用是 chat，每次工具执行是 execute_tool。

默认不带提示词、回复和工具结果的正文，只记长度：规范里这类属性要使用方主动打开，因为里面可能有个人信息。
正文留在有权限控制的事件日志里，需要时按任务 ID 去查。
"""


def spans(job, events, model, provider="dashscope", capture_content=False):
    t0 = events[0]["ts"]
    root = {"name": "invoke_agent oncall", "start": 0.0, "end": round(events[-1]["ts"] - t0, 2), "children": [],
            "attributes": {"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "oncall",
                           "gen_ai.provider.name": provider, "gen_ai.request.model": model,
                           "gen_ai.conversation.id": job["session_id"], "app.job_id": job["job_id"],
                           "app.config_id": job["config_id"], "app.attempts": job["attempts"]}}
    for e in events:
        p, t = e["payload"], round(e["ts"] - t0, 2)
        if e["type"] == "model":
            a = {"gen_ai.operation.name": "chat", "gen_ai.request.model": model,
                 "gen_ai.usage.input_tokens": p["usage"].get("prompt_tokens", 0),
                 "gen_ai.usage.output_tokens": p["usage"].get("completion_tokens", 0)}
            if capture_content:
                a["gen_ai.output.messages"] = p["message"]
            root["children"].append({"name": f"chat {model}", "end": t, "seconds": p.get("latency"), "attributes": a})
        elif e["type"] == "tool":
            a = {"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": p["name"], "app.ok": p["ok"],
                 "app.result_chars": len(p["result"])}
            if capture_content:
                a["app.result"] = p["result"]
            root["children"].append({"name": f"execute_tool {p['name']}", "end": t, "attributes": a})
        elif e["type"] in ("resume", "start", "final"):
            root["children"].append({"name": e["type"], "end": t, "attributes": {k: v for k, v in p.items() if k != "answer"}})
    return root


def render(root):
    a = root["attributes"]
    lines = [f"{root['name']}  {root['end']:.1f} 秒  会话 {a['gen_ai.conversation.id']}  任务 {a['app.job_id']}  "
             f"配置 {a['app.config_id']}  第 {a['app.attempts']} 次领取"]
    for c in root["children"]:
        ca = c["attributes"]
        if c["name"].startswith("chat"):
            lines.append(f"  {c['end']:>6.1f}s  chat           输入 {ca['gen_ai.usage.input_tokens']:>5}  输出 {ca['gen_ai.usage.output_tokens']:>4}"
                         f"  {c['seconds'] or 0:.1f} 秒")
        elif c["name"].startswith("execute_tool"):
            lines.append(f"  {c['end']:>6.1f}s  execute_tool   {ca['gen_ai.tool.name']:<16} {'成功' if ca['app.ok'] else '报错'}  {ca['app.result_chars']} 字")
        else:
            lines.append(f"  {c['end']:>6.1f}s  {c['name']:<14} {ca}")
    return "\n".join(lines)
