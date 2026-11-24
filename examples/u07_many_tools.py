"""单元七 · 接了一堆 MCP 服务器以后：40 个工具全给模型，还是让它先搜？

工具目录在 examples/mini_catalog.py：40 个工具，来自 12 个“服务器”，有几组故意相近。8 个问题，每个都有该用的工具。
  A. 全部给：40 个工具的定义每一轮都发。
  B. 按需搜索：一开始只给一个 search_tools(query) 工具；它按字面相似度返回最像的 5 个工具，
     程序把这 5 个的完整定义加进工具列表，模型下一轮就能调用（Anthropic 的工具搜索、Claude Code 的延迟加载都是这个思路）。
每个问题各跑 3 遍。只看“第一个真正的工具调用选得对不对”，选完就停，不真的执行。

    python examples/u07_many_tools.py            # 真调模型（约 120 次）
    python examples/u07_many_tools.py --replay
"""
import json

from _llm import replay_or_run
from mini_agent import run_agent
from mini_catalog import CATALOG, QUESTIONS

SYSTEM = "你是运维助手，用工具帮用户查问题或办事。先调用合适的工具，不要先回答。"
SEARCH = {"type": "function", "function": {
    "name": "search_tools", "description": "按关键词搜索可用的工具，返回最相关的 5 个工具的名字和说明；搜到之后就可以直接调用它们",
    "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "想做的事，例如“查 MySQL 慢查询”"}},
                   "required": ["query"]}}}
BY_NAME = {t["function"]["name"]: t for t in CATALOG}


def bigrams(s):
    s = s.lower()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def search(query, k=5):
    q = bigrams(query)
    scored = sorted(CATALOG, key=lambda t: -len(q & bigrams(t["function"]["name"].replace("__", " ") + t["function"]["description"])))
    return [t["function"]["name"] for t in scored[:k]]


def one(question, mode, seed):
    tools = list(CATALOG) if mode == "all" else [SEARCH]
    picked = []

    def execute(name, args):
        if name == "search_tools":
            names = search(args.get("query", ""))
            for n in names:
                if BY_NAME[n] not in tools:
                    tools.append(BY_NAME[n])                  # 同一个列表对象：下一轮调用就带上了新工具
            return json.dumps([{"name": n, "description": BY_NAME[n]["function"]["description"]} for n in names],
                              ensure_ascii=False)
        picked.append(name)
        return "（示例：不真的执行）"

    a = run_agent(question, SYSTEM, tools, execute, max_turns=6, stop_after_tool=lambda: bool(picked), seed=seed)
    searches = [c["args"].get("query") for t in a["trace"] for c in t["calls"] if c["name"] == "search_tools"]
    return {"picked": picked[0] if picked else None, "searches": searches, "llm_calls": len(a["trace"]),
            "prompt_tokens": sum(t["prompt_tokens"] for t in a["trace"]),
            "max_prompt": max(t["prompt_tokens"] for t in a["trace"])}


def run():
    return {mode: [dict(one(q, mode, seed), q=i) for i, (q, _) in enumerate(QUESTIONS) for seed in range(3)]
            for mode in ("all", "search")}


r = replay_or_run("u07_many_tools", run)
avg = lambda xs: sum(xs) / len(xs)  # noqa: E731
for mode, label in (("all", "A. 40 个工具全给"), ("search", "B. 先搜索，再加载")):
    runs = r[mode]
    right = sum(x["picked"] in QUESTIONS[x["q"]][1] for x in runs)
    print(f"{label}：选对 {right}/24，每题调模型 {avg([x['llm_calls'] for x in runs]):.1f} 次，"
          f"单次调用最大输入 {avg([x['max_prompt'] for x in runs]):,.0f} token，每题累计输入 {avg([x['prompt_tokens'] for x in runs]):,.0f} token")
    for x in runs:
        if x["picked"] not in QUESTIONS[x["q"]][1]:
            print(f"    选错：{QUESTIONS[x['q']][0]!r} → {x['picked']}（搜索词 {x['searches']}）")
print("\nB 组的搜索词（取每题第 1 遍）：", [x["searches"] for x in r["search"][::3]])
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
