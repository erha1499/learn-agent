"""最小的 Agent：一个 while 循环 + 工具调用（单元三），外加四个挂钩子的位置（单元四）。

    模型回复里有 tool_calls → 执行 → 结果追加进 messages → 再调模型
    模型回复里没有 tool_calls → 它认为做完了，循环结束

钩子都是可选的，不传时就是单元三那个最朴素的循环。harness 的机制挂在这些位置上，循环本身不改：
    before_tool(name, args, messages) -> str | None   执行前：返回字符串就拦下，不执行，把这段话当结果给模型
    after_tool(name, args, result)    -> str          执行后：改写结果（压缩、加证据编号……）
    stop_after_tool()                 -> bool         这一批工具执行完后：返回 True 就结束（例如结论已提交）
    on_finish(text)                   -> str | None   模型想结束时：返回字符串就作为一条用户消息追加进去，让它继续
"""
import json
import time

from _llm import chat


def run_agent(question, system, tools, execute, max_turns=10,
              before_tool=None, after_tool=None, stop_after_tool=None, on_finish=None, **params):
    messages = [{"role": "system", "content": system}, {"role": "user", "content": question}]
    trace = []                                                   # 只用来记录，不影响循环
    t0 = time.time()

    def done(stop, answer):
        return {"answer": answer, "stop": stop, "trace": trace, "messages": messages, "seconds": round(time.time() - t0, 1)}

    for turn in range(1, max_turns + 1):
        r = chat(messages, tools=tools, **params)                # 1. 把全部历史 + 工具定义发给模型
        messages.append(assistant_message(r))                    # 2. 模型的回复追加进历史
        trace.append({"turn": turn, "prompt_tokens": r["usage"].get("prompt_tokens", 0),
                      "completion_tokens": r["usage"].get("completion_tokens", 0),
                      "calls": [], "text": r["text"]})
        if not r["tool_calls"]:                                  # 3. 没要调工具：想结束
            nudge = on_finish(r["text"]) if on_finish else None
            if nudge is None:
                return done("done", r["text"])
            messages.append({"role": "user", "content": nudge})  # 钩子不让结束：补一句话，继续
            trace[-1]["nudge"] = nudge
            continue
        for call in r["tool_calls"]:                             # 4. 逐个执行模型要的工具
            name, raw = call["function"]["name"], call["function"]["arguments"]
            try:
                args = json.loads(raw or "{}")
            except json.JSONDecodeError:                         # 参数是模型写的字符串，可能不是合法 JSON
                args = None
            if args is None:
                args, result, blocked = raw, '{"error": "参数不是合法的 JSON"}', None
            else:
                blocked = before_tool(name, args, messages) if before_tool else None
                result = blocked if blocked is not None else execute(name, args)
                if after_tool:
                    result = after_tool(name, args, result)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})  # 5. 结果追加进历史
            trace[-1]["calls"].append({"name": name, "args": args, "result_chars": len(result),
                                       "blocked": blocked is not None})
        if stop_after_tool and stop_after_tool():
            return done("stopped_by_harness", None)
    return done("max_turns", None)


def assistant_message(r):
    """把模型的回复整理成可以原样发回去的 assistant 消息。"""
    m = {"role": "assistant", "content": r["text"]}
    if r["tool_calls"]:
        m["tool_calls"] = [{"id": c["id"], "type": "function",
                            "function": {"name": c["function"]["name"], "arguments": c["function"]["arguments"]}}
                           for c in r["tool_calls"]]
    return m
