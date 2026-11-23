"""单元二 · 一次回复里能要求调几个工具？

问题需要查两台实例。每种设置问 5 遍，数模型第一次回复里有几个 tool_calls：
  - 默认（不传 parallel_tool_calls）
  - parallel_tool_calls=True

    python examples/u02_parallel.py            # 真调模型（10 次）
    python examples/u02_parallel.py --replay
"""
from _llm import chat, replay_or_run
from mini_world import SYSTEM, TOOLS

Q = "对比一下 order-mysql-01 和 pay-mysql-03 的连接数，哪个更危险？"


def run():
    out = {}
    for key, extra in (("default", {}), ("parallel", {"parallel_tool_calls": True})):
        out[key] = []
        for seed in range(5):
            r = chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": Q}], tools=TOOLS, seed=seed, **extra)
            out[key].append([c["function"]["name"] + c["function"]["arguments"] for c in r["tool_calls"]])
    return {"question": Q, **out}


r = replay_or_run("u02_parallel", run)
print("问题：", r["question"], "\n")
for key, label in (("default", "默认"), ("parallel", "parallel_tool_calls=True")):
    counts = [len(x) for x in r[key]]
    print(f"{label:<26} 第一次回复里的工具调用个数：{counts}")
    print(f"{'':<26} 例：{r[key][0]}")
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
