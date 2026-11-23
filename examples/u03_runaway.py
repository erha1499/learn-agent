"""单元三 · 工具一直失败时，循环会怎样？模型会自己停吗？停下来时说了什么？

把 S4 的三个工具都换成"下游超时（504）"，上限 max_turns=15，跑 5 遍（每次换 seed）。记下：
跑了几轮、调了几次工具、是模型自己停的还是撞到上限、停下来时给出的根因。
两种系统提示词：原样（根因必须五选一）；加一句"查不到证据就写 根因: UNKNOWN"。

    python examples/u03_runaway.py            # 真调模型（最多 150 次）
    python examples/u03_runaway.py --replay
"""
import json

from _llm import replay_or_run
from mini_agent import run_agent
from mini_world import SCENARIOS, SYSTEM, TOOLS, verdict

S = SCENARIOS["S4"]


def always_timeout(name, args):
    return json.dumps({"error": "下游服务超时（504），请稍后重试"}, ensure_ascii=False)


ALLOW_UNKNOWN = SYSTEM + "。如果查不到能支持结论的证据，最后一行写：根因: UNKNOWN，并说明还缺什么"


def runs(system):
    out = []
    for seed in range(5):
        a = run_agent(S["question"], system, TOOLS, always_timeout, max_turns=15, seed=seed)
        out.append({"turns": len(a["trace"]), "tool_calls": sum(len(t["calls"]) for t in a["trace"]),
                    "stop": a["stop"], "pred": verdict(a["answer"]), "answer": a["answer"],
                    "tokens_in": sum(t["prompt_tokens"] for t in a["trace"])})
    return out


def run():
    return {"question": S["question"], "forced": runs(SYSTEM), "allow_unknown": runs(ALLOW_UNKNOWN)}


r = replay_or_run("u03_runaway", run)
print("问题：", r["question"], "（所有工具都返回 504）")
for key, label in (("forced", "根因必须五选一"), ("allow_unknown", "允许写 UNKNOWN")):
    print(f"\n--- {label}")
    for i, x in enumerate(r[key], 1):
        how = "模型自己停" if x["stop"] == "done" else "撞到 max_turns"
        print(f"第 {i} 遍：{x['turns']:>2} 轮，调工具 {x['tool_calls']:>2} 次，累计输入 {x['tokens_in']:>6} token，{how}，给出的根因：{x['pred']}")
    last = next((x["answer"] for x in r[key] if x["answer"]), "")
    print("停下来时的回答（取第 1 遍的结尾）：\n" + (last or "")[-260:])
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
