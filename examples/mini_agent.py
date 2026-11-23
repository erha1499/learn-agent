"""最小的 Agent：一个 while 循环 + 工具调用（单元三）。去掉记录和统计，核心就是 run_agent 里那十几行。

    模型回复里有 tool_calls → 执行 → 结果追加进 messages → 再调模型
    模型回复里没有 tool_calls → 它认为做完了，循环结束
"""
import json
import time

from _llm import chat


def run_agent(question, system, tools, execute, max_turns=10, **params):
    messages = [{"role": "system", "content": system}, {"role": "user", "content": question}]
    trace = []                                                   # 只用来记录，不影响循环
    t0 = time.time()
    for turn in range(1, max_turns + 1):
        r = chat(messages, tools=tools, **params)                # 1. 把全部历史 + 工具定义发给模型
        messages.append(assistant_message(r))                    # 2. 模型的回复追加进历史
        trace.append({"turn": turn, "prompt_tokens": r["usage"].get("prompt_tokens", 0),
                      "completion_tokens": r["usage"].get("completion_tokens", 0),
                      "calls": [], "text": r["text"]})
        if not r["tool_calls"]:                                  # 3. 没要调工具：结束
            return {"answer": r["text"], "stop": "done", "trace": trace, "messages": messages,
                    "seconds": round(time.time() - t0, 1)}
        for call in r["tool_calls"]:                             # 4. 逐个执行模型要的工具
            name, raw = call["function"]["name"], call["function"]["arguments"]
            try:
                args = json.loads(raw or "{}")
                result = execute(name, args)
            except json.JSONDecodeError:                         # 参数是模型写的字符串，可能不是合法 JSON
                args, result = raw, '{"error": "参数不是合法的 JSON"}'
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})  # 5. 结果追加进历史
            trace[-1]["calls"].append({"name": name, "args": args, "result_chars": len(result)})
    return {"answer": None, "stop": "max_turns", "trace": trace, "messages": messages,
            "seconds": round(time.time() - t0, 1)}


def assistant_message(r):
    """把模型的回复整理成可以原样发回去的 assistant 消息。"""
    m = {"role": "assistant", "content": r["text"]}
    if r["tool_calls"]:
        m["tool_calls"] = [{"id": c["id"], "type": "function",
                            "function": {"name": c["function"]["name"], "arguments": c["function"]["arguments"]}}
                           for c in r["tool_calls"]]
    return m
