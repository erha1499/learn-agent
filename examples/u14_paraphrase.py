"""单元十四 · 让模型帮忙扩充用例：同一个故障换 6 种说法，Agent 还做得对吗？

对迷你现场的 4 个场景，让模型把用户的提问改写成 6 种说法（每种说法有明确的要求），用 JSON 模式输出：
  口语化、信息更少（只说现象不说细节）、夹带无关信息、带一个错误的猜测、中英混杂、很长的抱怨
程序先检查每条改写是否合格：必须包含原来的实例名，不能出现别的实例名，不能和其他改写重复。
合格的改写，用单元三的 Agent 各跑 1 遍（seed=0），和原始问法比。

    python examples/u14_paraphrase.py            # 真调模型（约 100 次）
    python examples/u14_paraphrase.py --replay
"""
import json
import re

from _llm import chat, replay_or_run
from mini_agent import run_agent
from mini_world import ROOT_CAUSES, SCENARIOS, SYSTEM, TOOLS, execute, verdict

STYLES = {
    "口语化": "像在群里随口一问，口语、简短",
    "信息更少": "只说业务现象，不说技术细节和报错",
    "夹带无关信息": "前后夹杂一些和故障无关的事（比如别的需求、闲聊）",
    "错误猜测": "用户自带一个错误的猜测，猜一个和真实根因不同的原因（例如“是不是网络问题？”）",
    "中英混杂": "中英文混着说，像工程师日常的说法",
    "长篇抱怨": "情绪化、很长，抱怨影响有多大",
}
INSTANCES = {s["instance"] for s in SCENARIOS.values()}


def generate(s):
    prompt = (f"下面是值班群里用户报告故障的一句话：\n“{s['question']}”\n这个故障的真实根因是 {s['gold']}（{ROOT_CAUSES[s['gold']]}），"
              "改写时不要透露真实根因。\n请把它改写成以下 6 种说法，每种一条，必须保留实例名 " + s["instance"] + "，不要改变故障本身：\n"
              + "\n".join(f"- {k}：{v}" for k, v in STYLES.items())
              + '\n输出 JSON：{"variants": [{"style": "口语化", "text": "……"}, ...]}')
    r = chat([{"role": "user", "content": prompt}], response_format={"type": "json_object"}, seed=0)
    try:
        return json.loads(r["text"]).get("variants", [])
    except json.JSONDecodeError:
        return []


def check(s, v, seen):
    text = v.get("text", "")
    problems = []
    if s["instance"] not in text:
        problems.append("没有原来的实例名")
    others = [i for i in INSTANCES if i != s["instance"] and i in text]
    if others:
        problems.append(f"出现了别的实例 {others}")
    if text in seen:
        problems.append("和其他改写重复")
    if re.search(r"根因|" + s["gold"], text):
        problems.append("透露了根因")
    return problems


def run():
    out = {}
    for sid, s in SCENARIOS.items():
        variants = generate(s)
        seen, items = set(), []
        a = run_agent(s["question"], SYSTEM, TOOLS, execute, seed=0)
        items.append({"style": "原始问法", "text": s["question"], "problems": [], "pred": verdict(a["answer"]),
                      "calls": len(a["trace"])})
        for v in variants:
            problems = check(s, v, seen)
            seen.add(v.get("text", ""))
            item = {"style": v.get("style"), "text": v.get("text", ""), "problems": problems}
            if not problems:
                a = run_agent(v["text"], SYSTEM, TOOLS, execute, seed=0)
                item.update(pred=verdict(a["answer"]), calls=len(a["trace"]))
            items.append(item)
        out[sid] = items
    return out


r = replay_or_run("u14_paraphrase", run)
total = sum(len(v) - 1 for k, v in r.items() if k != "_meta")
bad = [(sid, x["style"], x["problems"]) for sid, v in r.items() if sid != "_meta" for x in v if x["problems"]]
print(f"生成改写 {total} 条，不合格 {len(bad)} 条：{bad}\n")
styles = ["原始问法"] + list(STYLES)
print(f"{'说法':<10}" + "".join(f"{sid:>6}" for sid in SCENARIOS) + "   答错时选了")
for st in styles:
    row, wrong = [], []
    for sid, s in SCENARIOS.items():
        x = next((i for i in r[sid] if i["style"] == st), None)
        if x is None or x.get("pred") is None:
            row.append("  —")
            continue
        ok = x["pred"] == s["gold"]
        row.append("  ✓" if ok else "  ✗")
        if not ok:
            wrong.append(f"{sid}→{x['pred']}")
    print(f"{st:<10}" + "".join(f"{c:>6}" for c in row) + "   " + ", ".join(wrong))
eg = next(x for x in r["S2"] if x["style"] == "错误猜测")
print(f"\n例：S2 的“错误猜测”改写：{eg['text']!r}")
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
