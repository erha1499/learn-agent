"""单元五 · 子 Agent：一次要查 4 台库，自己挨个查，还是每台交给一个子 Agent？

  A. 单个 Agent：3 个查询工具，4 台库的所有查询结果都留在它自己的上下文里。
  B. 主 Agent + 子 Agent：主 Agent 只有一个工具 investigate(instance)。每次调用，程序另起一个全新的
     run_agent（子 Agent，有 3 个查询工具），子 Agent 查完只把最后的结论文字交回来，中间过程不进主 Agent 的上下文。
各跑 3 遍，比：4 台各自答对几台、主 Agent 单次调用的最大输入（上下文峰值）、所有 Agent 加起来的 token 和调用次数。
两种现场：
  干净：和单元三一样，每个工具结果都很短。
  嘈杂：错误日志工具不分页、一次返回全部，每台的错误日志前面多了 300 行无关的断连告警（单元四那种刷屏）。

    python examples/u05_subagent.py            # 真调模型（约 120 次，嘈杂那组每次输入上万 token）
    python examples/u05_subagent.py --replay
"""
import copy
import re

from _llm import replay_or_run
from mini_agent import run_agent
from mini_world import SCENARIOS, SYSTEM, TOOLS, execute, verdict

INSTANCES = {s["instance"]: s["gold"] for s in SCENARIOS.values()}
QUESTION = ("今天这 4 台库都有用户报问题：" + "、".join(INSTANCES) + "。逐台查一下，各自是什么根因？"
            "最后每台一行，格式：实例名: 根因ID")
PARENT_SYSTEM = SYSTEM.replace("回答最后一行写：根因: <ID>", "按用户要求的格式给出每台实例的根因")
INVESTIGATE = {"type": "function", "function": {
    "name": "investigate",
    "description": "派一个助手去排查一台实例，它会自己查监控和日志，返回结论",
    "parameters": {"type": "object", "properties": {"instance": {"type": "string"}}, "required": ["instance"]}}}


def parse(answer):
    found = dict(re.findall(r"([a-z]+-mysql-\d+)\**\s*[:：]\s*\**\s*([A-Z_]+)", answer or ""))
    return {inst: found.get(inst) for inst in INSTANCES}


def stats(trace):
    return {"calls": len(trace), "tokens": sum(t["prompt_tokens"] + t["completion_tokens"] for t in trace),
            "peak": max(t["prompt_tokens"] for t in trace)}


NOISY_TOOLS = copy.deepcopy(TOOLS)
NOISY_TOOLS[2]["function"]["description"] = "查询一个 MySQL 实例最近的错误日志（返回全部）"
NOISY_TOOLS[2]["function"]["parameters"]["properties"].pop("limit")
NOISE = ["2026-11-24 09:%02d:%02d [Warning] Aborted connection %d to db: 'app' user: 'app' host: '10.9.%d.%d' "
         "(Got an error reading communication packets)" % (i // 60 % 60, i % 60, 50000 + i, i % 5, i % 200) for i in range(300)]


def noisy_execute(name, args):
    if name == "query_error_log":
        real = execute(name, {**args, "limit": 10 ** 6})
        return real if real.startswith('{"error"') else "\n".join(NOISE + [real])
    return execute(name, args)


def single(seed, tools=TOOLS, ex=execute):
    a = run_agent(QUESTION, PARENT_SYSTEM, tools, ex, max_turns=20, seed=seed)
    s = stats(a["trace"])
    return {"pred": parse(a["answer"]), "parent_peak": s["peak"], "parent_calls": s["calls"],
            "total_calls": s["calls"], "total_tokens": s["tokens"]}


def with_subagents(seed, tools=TOOLS, ex=execute):
    children = []

    def run_child(name, args):
        if name != "investigate":
            return '{"error": "没有这个工具"}'
        c = run_agent(f"{args.get('instance')} 有用户报问题，帮忙查一下根因", SYSTEM, tools, ex, seed=seed)
        children.append(stats(c["trace"]) | {"verdict": verdict(c["answer"])})
        return c["answer"] or "子 Agent 没有给出结论"

    a = run_agent(QUESTION, PARENT_SYSTEM, [INVESTIGATE], run_child, max_turns=10, seed=seed)
    p = stats(a["trace"])
    return {"pred": parse(a["answer"]), "parent_peak": p["peak"], "parent_calls": p["calls"],
            "children": children, "total_calls": p["calls"] + sum(c["calls"] for c in children),
            "total_tokens": p["tokens"] + sum(c["tokens"] for c in children)}


def run():
    out = {}
    for world, tools, ex in (("clean", TOOLS, execute), ("noisy", NOISY_TOOLS, noisy_execute)):
        out[world] = {"single": [single(s, tools, ex) for s in range(3)],
                      "subagent": [with_subagents(s, tools, ex) for s in range(3)]}
    return out


r = replay_or_run("u05_subagent", run)
avg = lambda xs: sum(xs) / len(xs)  # noqa: E731
print("问题：", QUESTION)
for world, wlabel in (("clean", "干净现场"), ("noisy", "嘈杂现场（每台错误日志多 300 行噪音）")):
    print(f"\n--- {wlabel}")
    for mode, label in (("single", "A. 单个 Agent"), ("subagent", "B. 主 Agent + 子 Agent")):
        runs = r[world][mode]
        right = [sum(x["pred"][i] == g for i, g in INSTANCES.items()) for x in runs]
        print(f"{label}：每遍答对 {right}（共 4 台），主 Agent 上下文峰值 {avg([x['parent_peak'] for x in runs]):,.0f} token，"
              f"主 Agent 调模型 {avg([x['parent_calls'] for x in runs]):.1f} 次；"
              f"所有 Agent 合计调模型 {avg([x['total_calls'] for x in runs]):.1f} 次、{avg([x['total_tokens'] for x in runs]):,.0f} token")
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
