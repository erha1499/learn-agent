"""执行一个任务：从事件日志恢复，每一步先写事件再往下走。worker 死在哪一步，下一个 worker 都能接着跑。

恢复时，最后一条模型回复里还没有结果的工具调用要补执行。这里的工具都是只读查询，补执行是安全的；
有副作用的工具，要按“任务 ID + 动作”做幂等（单元十二）。
"""
import json

from mini_agent import assistant_message
from mini_world import verdict


class Crash(Exception):
    """模拟 worker 进程在这一刻死掉：任务状态不更新，租约到期后由别的 worker 接手。"""


def rebuild(cfg, question, events):
    messages = [{"role": "system", "content": cfg["system_prompt"]}, {"role": "user", "content": question}]
    turns = tokens = 0
    for e in events:
        p = e["payload"]
        if e["type"] == "model":
            messages.append(p["message"])
            turns += 1
            tokens += p["usage"].get("prompt_tokens", 0) + p["usage"].get("completion_tokens", 0)
        elif e["type"] == "tool":
            messages.append({"role": "tool", "tool_call_id": p["id"], "content": p["result"]})
    done = {m["tool_call_id"] for m in messages if m["role"] == "tool"}
    last = next((m for m in reversed(messages) if m["role"] == "assistant"), None)
    pending = [c for c in (last or {}).get("tool_calls") or [] if c["id"] not in done]
    return messages, pending, turns, tokens


def run_job(job, cfg, cid, gateway, store, execute, lease_s, fault=None):
    jid = job["job_id"]
    old = store.events(jid)
    if old:
        store.append(jid, "resume", {"attempt": job["attempts"], "worker": job["worker"], "after_seq": old[-1]["seq"]})
    else:
        store.append(jid, "start", {"config_id": cid, "worker": job["worker"]})
    messages, pending, turns, tokens = rebuild(cfg, job["question"], old)
    limits = cfg["limits"]
    while True:
        store.renew(jid, lease_s)
        for call in pending:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = None
            result = execute(name, args) if isinstance(args, dict) else '{"error": "参数不是合法的 JSON"}'
            store.append(jid, "tool", {"id": call["id"], "name": name, "args": args, "result": result,
                                       "ok": not result.startswith('{"error"')})
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
            if fault:
                fault(job, store.events(jid))
        if turns >= limits["max_turns"] or tokens >= limits["max_tokens_per_job"]:
            result = {"answer": None, "pred": None, "stop": "budget"}
            store.append(jid, "final", result)
            return result
        r = gateway.call(messages=messages, model=cfg["model"], tools=cfg["tools"], **cfg["params"])
        msg = assistant_message(r)
        store.append(jid, "model", {"message": msg, "usage": r.get("usage", {}), "latency": r.get("latency")})
        messages.append(msg)
        turns += 1
        tokens += r["usage"].get("prompt_tokens", 0) + r["usage"].get("completion_tokens", 0)
        pending = msg.get("tool_calls") or []
        if not pending:
            result = {"answer": r["text"], "pred": verdict(r["text"]), "stop": "done", "turns": turns, "tokens": tokens}
            store.append(jid, "final", result)
            return result
