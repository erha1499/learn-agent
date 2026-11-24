"""单元十二 · 进程在半路崩了，怎么接着跑？会不会把工单建两遍？

S1（order-mysql-01 下单报错）。Agent 查清根因后要调用 create_ticket 建一张工单，再回复用户。
在工单建好之后、回复用户之前，进程“崩溃”。六种恢复方式，各跑 3 遍（每次换 seed）：
  R1 从头重跑，工单系统不去重
  R2 从头重跑，工单系统按“工具名 + 参数”去重（幂等键来自模型写的参数）
  R3 从头重跑，工单系统按“任务 ID + 动作”去重（幂等键来自业务身份）
  R4 从事件日志恢复：崩在“执行完、已记账”之后
  R5 从事件日志恢复：崩在“执行完、还没记账”之间，工单系统不去重
  R6 同 R5，但工单系统按“任务 ID + 动作”去重
事件日志：每条消息、每次模型调用（耗时、token）都追加一条记录。恢复 = 重放日志里的消息，
发现模型要求的工具调用还没有结果，就补执行，再接着循环。
记下：最后建了几张工单、崩溃后又调了几次模型、多花了多少 token。顺便把一次运行的日志还原成一条轨迹。

    python examples/u12_resume.py            # 真调模型（约 100 次）
    python examples/u12_resume.py --replay
"""
import json
import time

from _llm import chat, replay_or_run
from mini_agent import assistant_message
from mini_world import SCENARIOS, SYSTEM, TOOLS, execute, verdict

S = SCENARIOS["S1"]
SYS = SYSTEM + "。查清根因后，先调用 create_ticket 建一张工单（标题写明实例和根因），再回复用户"
TICKET = {"type": "function", "function": {"name": "create_ticket", "description": "在工单系统里建一张故障工单",
          "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "severity": {"type": "string", "enum": ["P0", "P1", "P2"]}},
                         "required": ["title", "severity"]}}}


class Crash(Exception):
    pass


class TicketSystem:
    def __init__(self, idem):
        self.idem, self.tickets, self.keys = idem, [], {}

    def create(self, task_id, args):
        key = {"args": json.dumps(args, sort_keys=True, ensure_ascii=False), "task": f"{task_id}:create_ticket"}.get(self.idem)
        if key and key in self.keys:
            return f"工单已存在：{self.keys[key]}（幂等键命中，没有重复创建）"
        tid = f"INC-{len(self.tickets) + 1001}"
        self.tickets.append({"id": tid, **args})
        if key:
            self.keys[key] = tid
        return f"已创建工单 {tid}"


def make_exec(tickets, task_id):
    def ex(name, args):
        return tickets.create(task_id, args) if name == "create_ticket" else execute(name, args)
    return ex


def loop(messages, events, ex, crash_at=None, seed=None, max_turns=10):
    """单元三的循环，多了两件事：每一步写事件日志；在指定位置模拟崩溃。"""
    def pending():                                    # 恢复时：最后一条 assistant 里还没有结果的工具调用
        done = {m["tool_call_id"] for m in messages if m["role"] == "tool"}
        last = next((m for m in reversed(messages) if m["role"] == "assistant"), None)
        return [c for c in (last or {}).get("tool_calls", []) if c["id"] not in done]

    def run_calls(calls):
        for c in calls:
            name, args = c["function"]["name"], json.loads(c["function"]["arguments"] or "{}")
            t0 = time.time()
            result = ex(name, args)
            events.append({"type": "tool", "name": name, "seconds": round(time.time() - t0, 3)})
            if crash_at == "after_exec" and name == "create_ticket":
                raise Crash("执行完、还没记账")
            msg = {"role": "tool", "tool_call_id": c["id"], "content": result}
            messages.append(msg)
            events.append({"type": "message", "message": msg})
            if crash_at == "after_log" and name == "create_ticket":
                raise Crash("执行完、已记账")

    run_calls(pending())
    for _ in range(max_turns):
        t0 = time.time()
        r = chat(messages, tools=TOOLS + [TICKET], seed=seed)
        events.append({"type": "llm", "seconds": round(time.time() - t0, 2), "prompt_tokens": r["usage"]["prompt_tokens"],
                       "completion_tokens": r["usage"]["completion_tokens"]})
        msg = assistant_message(r)
        messages.append(msg)
        events.append({"type": "message", "message": msg})
        if not r["tool_calls"]:
            return r["text"]
        run_calls(r["tool_calls"])
    return None


def replay(events):
    return [e["message"] for e in events if e["type"] == "message"]


def one(strategy, seed):
    idem = {"R2": "args", "R3": "task", "R6": "task"}.get(strategy)
    crash_at = "after_exec" if strategy in ("R5", "R6") else "after_log"
    tickets, task_id = TicketSystem(idem), f"case-S1-{seed}"
    ex = make_exec(tickets, task_id)
    start = [{"role": "system", "content": SYS}, {"role": "user", "content": S["question"]}]
    events = [{"type": "message", "message": m} for m in start]
    try:
        loop(list(start), events, ex, crash_at=crash_at, seed=seed)
    except Crash:
        pass
    before = sum(1 for e in events if e["type"] == "llm")
    after_events = []
    if strategy in ("R1", "R2", "R3"):                 # 从头重跑：丢掉日志，重新开始
        answer = loop(list(start), after_events, ex, seed=seed)
    else:                                             # 从日志恢复：重放消息，补执行没有结果的调用，接着跑
        answer = loop(replay(events), after_events, ex, seed=seed)
    llm_after = [e for e in after_events if e["type"] == "llm"]
    return {"tickets": tickets.tickets, "llm_before": before, "llm_after": len(llm_after),
            "tokens_after": sum(e["prompt_tokens"] + e["completion_tokens"] for e in llm_after),
            "pred": verdict(answer), "events": events + after_events}


def run():
    return {s: [one(s, seed) for seed in range(3)] for s in ("R1", "R2", "R3", "R4", "R5", "R6")}


r = replay_or_run("u12_resume", run)
labels = {"R1": "R1 从头重跑，不去重", "R2": "R2 从头重跑，按参数去重", "R3": "R3 从头重跑，按任务 ID 去重",
          "R4": "R4 日志恢复（崩在已记账后）", "R5": "R5 日志恢复（崩在执行和记账之间），不去重", "R6": "R6 同 R5，按任务 ID 去重"}
avg = lambda xs: sum(xs) / len(xs)  # noqa: E731
print(f"{'':<36}{'工单数':>6}{'崩溃前调模型':>10}{'崩溃后调模型':>10}{'崩溃后 token':>12}")
for s, runs in r.items():
    if s == "_meta":
        continue
    print(f"{labels[s]:<36}{str([len(x['tickets']) for x in runs]):>8}{avg([x['llm_before'] for x in runs]):>10.1f}"
          f"{avg([x['llm_after'] for x in runs]):>10.1f}{avg([x['tokens_after'] for x in runs]):>12,.0f}")
titles = [[t["title"] for t in x["tickets"]] for x in r["R2"]]
print("\nR2 每遍建出的工单标题：", titles)
print("\n一次运行（R4 第 1 遍）的事件日志还原成轨迹：")
t = 0.0
for e in r["R4"][0]["events"]:
    if e["type"] == "llm":
        print(f"  调模型   {e['seconds']:>5.2f} 秒  输入 {e['prompt_tokens']:>5}  输出 {e['completion_tokens']:>4}")
    elif e["type"] == "tool":
        print(f"  执行工具 {e['name']}")
    elif e["message"]["role"] == "tool":
        print(f"    结果入账：{e['message']['content'][:40]!r}")
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
