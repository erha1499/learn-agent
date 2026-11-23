"""单元二 · 一次工具调用，从头到尾发生了什么？

同一个问题问三次：
  A. 不给工具：模型只能凭经验猜。
  B. 给工具：看模型回的原始消息（content、tool_calls、finish_reason）。
  C. 我们执行工具、把结果按协议发回去：看第二次调用的完整 messages 和最终回答。
再算一笔账：3 个工具的定义本身占多少输入 token。

    python examples/u02_tool_call.py            # 真调模型（4 次）
    python examples/u02_tool_call.py --replay   # 看录好的结果
"""
import json

from _llm import chat, replay_or_run
from mini_agent import assistant_message
from mini_world import SCENARIOS, SYSTEM, TOOLS, execute

Q = SCENARIOS["S1"]["question"]


def run():
    base = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": Q}]
    a = chat(base, seed=1)                                   # A. 不给工具
    b = chat(base, tools=TOOLS, seed=1)                      # B. 给工具
    msgs = base + [assistant_message(b)]
    for call in b["tool_calls"]:                             # C. 我们执行，结果按协议发回去
        msgs.append({"role": "tool", "tool_call_id": call["id"],
                     "content": execute(call["function"]["name"], json.loads(call["function"]["arguments"]))})
    c = chat(msgs, tools=TOOLS, seed=1)
    return {"question": Q,
            "A_no_tools": {"text": a["text"], "usage": a["usage"]},
            "B_with_tools": {"message": b["message"], "finish_reason": b["finish_reason"], "usage": b["usage"]},
            "C_second_call": {"messages_sent": msgs, "text": c["text"], "finish_reason": c["finish_reason"], "usage": c["usage"],
                              "tool_calls": [x["function"]["name"] + x["function"]["arguments"] for x in c["tool_calls"]]},
            "tool_def_tokens": b["usage"]["prompt_tokens"] - a["usage"]["prompt_tokens"]}


r = replay_or_run("u02_tool_call", run)
print("问题：", r["question"])
print("\n=== A. 不给工具 ===")
t = r["A_no_tools"]["text"]
print(t[:160], "\n……\n", t[-420:]) if len(t) > 600 else print(t)
print("\n=== B. 给工具：模型回的原始消息 ===")
print(json.dumps(r["B_with_tools"]["message"], ensure_ascii=False, indent=1))
print("finish_reason =", r["B_with_tools"]["finish_reason"])
print("\n=== C. 执行工具后，第二次调用发出去的 messages ===")
for m in r["C_second_call"]["messages_sent"]:
    body = m.get("content") or ""
    extra = f"  tool_calls={[c['function']['name'] + c['function']['arguments'] for c in m['tool_calls']]}" if m.get("tool_calls") else ""
    extra += f"  tool_call_id={m['tool_call_id']}" if m.get("tool_call_id") else ""
    print(f"[{m['role']}] {body[:80]!r}{extra}")
print("\n第二次调用的回复：", r["C_second_call"]["text"].strip())
print("finish_reason =", r["C_second_call"]["finish_reason"], " 还想调：", r["C_second_call"]["tool_calls"])
print("\n=== token ===")
for k in ("A_no_tools", "B_with_tools", "C_second_call"):
    u = r[k]["usage"]
    print(f"{k:<14} 输入 {u['prompt_tokens']:>5}  输出 {u['completion_tokens']:>4}")
print(f"3 个工具的定义占输入 token：{r['tool_def_tokens']}")
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
