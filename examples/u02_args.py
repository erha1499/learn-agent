"""单元二 · 参数从哪来？用户没说实例名时，模型会先问，还是自己编一个？

提问里故意不给实例名，工具 get_metrics 又要求必填 instance。每种写法问 10 遍（每次换 seed），数一数：
  - 没调工具、反问用户
  - 调了工具，instance 是编出来的
参数描述有四种写法（2×2）：带不带例子"例如 order-mysql-01"；加不加一句"不知道就先问用户，不要猜"。

    python examples/u02_args.py            # 真调模型（40 次）
    python examples/u02_args.py --replay
"""
import copy
from collections import Counter

from _llm import chat, replay_or_run
from mini_world import SYSTEM, TOOLS

Q = "数据库连接数现在多少？会不会快满了"


def variant(example, hint):
    tools = copy.deepcopy(TOOLS[:1])
    desc = "实例名，例如 order-mysql-01" if example else "实例名"
    if hint:
        desc += "。必须是用户明确给出的实例名，不知道就先问用户，不要猜"
    tools[0]["function"]["parameters"]["properties"]["instance"]["description"] = desc
    out = []
    for seed in range(10):
        r = chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": Q}], tools=tools, seed=seed)
        if r["tool_calls"]:
            out.append({"kind": "invented", "args": [c["function"]["arguments"] for c in r["tool_calls"]]})
        else:
            out.append({"kind": "asked", "text": r["text"][:120]})
    return out


def run():
    return {"question": Q, "variants": {k: variant(*flags) for k, flags in VARIANTS.items()}}


VARIANTS = {"带例子": (True, False), "带例子 + 不知道就问": (True, True),
            "不带例子": (False, False), "不带例子 + 不知道就问": (False, True)}


r = replay_or_run("u02_args", run)
print("提问：", r["question"], "（没给实例名）\n")
for label, runs in r["variants"].items():
    kinds = Counter(x["kind"] for x in runs)
    names = Counter(a for x in runs if x["kind"] == "invented" for a in x["args"])
    print(f"{label:<14}反问用户 {kinds['asked']:>2} 次，编了实例名去调工具 {kinds['invented']:>2} 次")
    for a, n in names.most_common():
        print(f"    编出来的参数 {a} ×{n}")
    asked = [x["text"] for x in runs if x["kind"] == "asked"]
    if asked:
        print(f"    反问的样子：{asked[0]!r}")
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
