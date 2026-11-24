"""单元四 · 模型不换、循环不改，只换 harness：三个问题各被哪个机制挡住？

  A. 参数守卫：用户没说实例名，模型会自己填一个（单元二）。不加守卫时，这次调用真的会执行吗？
  B. 结果压缩：错误日志 400 行刷屏，原样塞给模型要花多少 token？合并重复行以后呢？
  C. 提交门：工具全部超时（单元三），结论必须引用真实的证据编号才能提交，模型会怎么做？
  D. 回归：三个机制一起打开，单元三的 4 个正常场景还做得对吗？多花多少？

    python examples/u04_harness.py            # 真调模型（约 150 次，日志刷屏那组每次输入上万 token）
    python examples/u04_harness.py --replay
"""
import copy
import json

from _llm import replay_or_run
from mini_agent import run_agent
from mini_harness import SYSTEM_GATE, Harness
from mini_world import FLOOD, SCENARIOS, SYSTEM, TOOLS, execute, verdict

Q_NO_INSTANCE = "数据库连接数现在多少？会不会快满了"

TOOLS_NAIVE = copy.deepcopy(TOOLS)          # B 组：一个“朴素”的错误日志工具，不分页，一次返回全部
TOOLS_NAIVE[2]["function"]["description"] = "查询一个 MySQL 实例最近的错误日志（返回全部）"
TOOLS_NAIVE[2]["function"]["parameters"]["properties"].pop("limit")


def execute_naive(name, args):
    if name == "query_error_log":
        return execute(name, {**args, "limit": 10 ** 6})
    return execute(name, args)


def always_timeout(name, args):
    return json.dumps({"error": "下游服务超时（504），请稍后重试"}, ensure_ascii=False)


def summary(a, h=None):
    calls = [c for t in a["trace"] for c in t["calls"]]
    return {"stop": a["stop"], "turns": len(a["trace"]),
            "prompt_tokens": sum(t["prompt_tokens"] for t in a["trace"]),
            "max_prompt": max(t["prompt_tokens"] for t in a["trace"]),
            "tokens": sum(t["prompt_tokens"] + t["completion_tokens"] for t in a["trace"]),
            "calls": [{"name": c["name"], "args": c["args"], "chars": c["result_chars"], "blocked": c["blocked"]} for c in calls],
            "answer": (a["answer"] or "")[-300:], "pred": verdict(a["answer"]),
            "accepted": h.accepted if h else None, "rejections": h.rejections if h else [],
            "nudges": h.nudges if h else 0}


def part_a():
    out = {}
    for mode in ("bare", "guard"):
        out[mode] = []
        for seed in range(10):
            h = Harness(guard=(mode == "guard"))
            a = run_agent(Q_NO_INSTANCE, SYSTEM, TOOLS, execute, before_tool=h.hooks()["before_tool"], seed=seed)
            out[mode].append(summary(a))
    return out


def part_b():
    out = {}
    for mode in ("bare", "compress"):
        out[mode] = []
        for seed in range(5):
            h = Harness(compress=(mode == "compress"))
            a = run_agent(FLOOD["question"], SYSTEM, TOOLS_NAIVE, execute_naive, after_tool=h.hooks()["after_tool"], seed=seed)
            out[mode].append(summary(a))
    return out


def part_c():
    out = []
    for seed in range(5):
        h = Harness(gate=True)
        a = run_agent(SCENARIOS["S4"]["question"], SYSTEM_GATE, h.tools(TOOLS), h.execute(always_timeout),
                      max_turns=15, seed=seed, **h.hooks())
        out.append(summary(a, h))
    return out


def part_d():
    out = {}
    for sid, s in SCENARIOS.items():
        out[sid] = []
        for seed in range(3):
            h = Harness(guard=True, compress=True, gate=True)
            a = run_agent(s["question"], SYSTEM_GATE, h.tools(TOOLS), h.execute(execute), seed=seed, **h.hooks())
            out[sid].append(summary(a, h))
    return out


def run():
    return {"A": part_a(), "B": part_b(), "C": part_c(), "D": part_d()}


r = replay_or_run("u04_harness", run)
avg = lambda xs: sum(xs) / len(xs)  # noqa: E731

print(f"=== A. 参数守卫  提问：{Q_NO_INSTANCE}（没给实例名）")
for mode, label in (("bare", "不加守卫"), ("guard", "加守卫")):
    runs = r["A"][mode]
    wrong = [x for x in runs if any(not c["blocked"] and c["args"].get("instance") for c in x["calls"])]
    blocked = sum(c["blocked"] for x in runs for c in x["calls"])
    print(f"{label}：10 遍里 {len(wrong)} 遍真的查了一台用户没提过的实例，守卫拦下 {blocked} 次调用")
    print(f"    结尾（第 1 遍）：{runs[0]['answer'][-120:]!r}")

print(f"\n=== B. 结果压缩  {FLOOD['question']}（错误日志 400 行，只有 10 行是线索）")
for mode, label in (("bare", "原样返回"), ("compress", "合并重复行")):
    runs = r["B"][mode]
    log_chars = [c["chars"] for x in runs for c in x["calls"] if c["name"] == "query_error_log"]
    right = sum(x["pred"] == FLOOD["gold"] for x in runs)
    print(f"{label}：答对 {right}/5，每例累计输入 {avg([x['prompt_tokens'] for x in runs]):,.0f} token，"
          f"单次调用最多 {max(x['max_prompt'] for x in runs):,} token，错误日志结果 {max(log_chars) if log_chars else 0:,} 字符，"
          f"答错时选了 {[x['pred'] for x in runs if x['pred'] != FLOOD['gold']]}")

print("\n=== C. 提交门  工具全部超时")
for i, x in enumerate(r["C"], 1):
    rej = [f"{j['root_cause']}{j['evidence']}" for j in x["rejections"]]
    print(f"第 {i} 遍：{x['turns']} 轮，被退回 {len(x['rejections'])} 次 {rej}，提醒 {x['nudges']} 次，最终提交 {x['accepted']}")

print("\n=== D. 回归  三个机制都打开，4 个正常场景各 3 遍")
allruns = []
for sid, runs in r["D"].items():
    right = sum((x["accepted"] or {}).get("root_cause") == SCENARIOS[sid]["gold"] for x in runs)
    allruns += runs
    print(f"{sid}：答对 {right}/3，每例 token {avg([x['tokens'] for x in runs]):,.0f}，调模型 {avg([x['turns'] for x in runs]):.1f} 次，"
          f"被退回 {sum(len(x['rejections']) for x in runs)} 次，提醒 {sum(x['nudges'] for x in runs)} 次")
right = sum((x["accepted"] or {}).get("root_cause") == SCENARIOS[sid]["gold"] for sid, runs in r["D"].items() for x in runs)
print(f"合计：答对 {right}/12，每例 token {avg([x['tokens'] for x in allruns]):,.0f}，调模型 {avg([x['turns'] for x in allruns]):.1f} 次")
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
