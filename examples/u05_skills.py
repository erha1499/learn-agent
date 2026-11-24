"""单元五 · Skills：5 份排查手册，全部塞进系统提示词，还是先给目录、用到再加载？

手册在 examples/mini_skills/<名字>/SKILL.md，开头的 frontmatter 里有 name 和 description。
  A. 全部塞进去：5 份手册全文拼在系统提示词后面，每一轮都发。
  B. 按需加载：系统提示词里只放目录（名字 + 一句描述），再给一个 load_skill(name) 工具，模型要看哪份才读哪份。
4 个场景各跑 2 遍，比：答对几次、每次调用平均输入 token、每例累计输入 token、B 组读了哪些手册。
再加一个手册真正派得上用场的情况：S4 的工具全部超时（单元三），提示词仍要求根因五选一，
而 network 手册里写着“只有排除法时，结论应写 UNKNOWN”。不给手册、全部塞进去、按需加载，各跑 5 遍。

    python examples/u05_skills.py            # 真调模型（约 100 次）
    python examples/u05_skills.py --replay
"""
import json
import os
import re

from _llm import replay_or_run
from mini_agent import run_agent
from mini_world import SCENARIOS, SYSTEM, TOOLS, execute, verdict

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mini_skills")


def load_all():
    skills = {}
    for name in sorted(os.listdir(DIR)):
        text = open(os.path.join(DIR, name, "SKILL.md"), encoding="utf-8").read()
        desc = re.search(r"^description:\s*(.+)$", text, re.M).group(1)
        skills[name] = {"description": desc, "body": text.split("---", 2)[2].strip()}
    return skills


SKILLS = load_all()
SYSTEM_ALL = SYSTEM + "\n\n下面是排查手册：\n\n" + "\n\n".join(s["body"] for s in SKILLS.values())
SYSTEM_INDEX = (SYSTEM + "\n\n可用的排查手册（需要时用 load_skill 读全文）：\n"
                + "\n".join(f"- {n}：{s['description']}" for n, s in SKILLS.items()))
LOAD = {"type": "function", "function": {
    "name": "load_skill", "description": "读取一份排查手册的全文",
    "parameters": {"type": "object", "properties": {"name": {"type": "string", "enum": list(SKILLS)}}, "required": ["name"]}}}


def execute_with_skills(name, args):
    if name == "load_skill":
        s = SKILLS.get(args.get("name"))
        return s["body"] if s else json.dumps({"error": "没有这份手册"}, ensure_ascii=False)
    return execute(name, args)


def one(system, tools, ex, s, seed):
    a = run_agent(s["question"], system, tools, ex, seed=seed)
    calls = [c for t in a["trace"] for c in t["calls"]]
    return {"pred": verdict(a["answer"]), "gold": s["gold"], "llm_calls": len(a["trace"]),
            "prompt_tokens": sum(t["prompt_tokens"] for t in a["trace"]),
            "loaded": [c["args"].get("name") for c in calls if c["name"] == "load_skill"]}


def timeout(name, args):
    if name == "load_skill":
        return execute_with_skills(name, args)
    return json.dumps({"error": "下游服务超时（504），请稍后重试"}, ensure_ascii=False)


def run():
    s4 = SCENARIOS["S4"]
    return {"all": [one(SYSTEM_ALL, TOOLS, execute, s, seed) for s in SCENARIOS.values() for seed in range(2)],
            "index": [one(SYSTEM_INDEX, TOOLS + [LOAD], execute_with_skills, s, seed)
                      for s in SCENARIOS.values() for seed in range(2)],
            "fail": {"none": [one(SYSTEM, TOOLS, timeout, s4, seed) for seed in range(5)],
                     "all": [one(SYSTEM_ALL, TOOLS, timeout, s4, seed) for seed in range(5)],
                     "index": [one(SYSTEM_INDEX, TOOLS + [LOAD], timeout, s4, seed) for seed in range(5)]}}


r = replay_or_run("u05_skills", run)
avg = lambda xs: sum(xs) / len(xs)  # noqa: E731
print(f"5 份手册共 {sum(len(s['body']) for s in SKILLS.values()):,} 字符\n")
for mode, label in (("all", "A. 全部塞进系统提示词"), ("index", "B. 只放目录，按需加载")):
    runs = r[mode]
    right = sum(x["pred"] == x["gold"] for x in runs)
    per_call = sum(x["prompt_tokens"] for x in runs) / sum(x["llm_calls"] for x in runs)
    print(f"{label}：答对 {right}/8，每次调用平均输入 {per_call:,.0f} token，每例累计输入 {avg([x['prompt_tokens'] for x in runs]):,.0f} token，"
          f"每例调模型 {avg([x['llm_calls'] for x in runs]):.1f} 次")
    if mode == "index":
        for x in runs:
            print(f"    {x['gold']:<16} 读了 {x['loaded']}  结论 {x['pred']}")
print("\n--- 工具全部超时（S4），根因仍要求五选一")
for mode, label in (("none", "不给手册"), ("all", "全部塞进系统提示词"), ("index", "只放目录，按需加载")):
    runs = r["fail"][mode]
    print(f"{label}：给出的根因 {[x['pred'] for x in runs]}，读了 {[x['loaded'] for x in runs]}")
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
