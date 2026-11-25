"""单元十九 · 模拟一段线上流量：Agent 答错了，没有标准答案时，你能从哪些信号看出来？

12 批会话，每批 20 个，问题从迷你评测集的 20 条用例里随机抽（固定种子）。前 6 批正常；
从第 7 批起模拟一次基础设施变更：错误日志服务第一次调用都超时（504），再调一次才正常。
每个会话录下：调了哪些工具、每次的返回、最后的回答、token、耗时。为了算“一致性”，同一个问题在同样的条件下再悄悄跑 2 遍。
最后让另一个模型（qwen-max）当评委：只给它工具返回和结论，问“结论有没有被这些数据支持”，不给它正确答案。

真实根因在模拟里是知道的，但只用来检验信号准不准；线上你看不到它。分析见 u19_monitor.py。

    python examples/u19_traffic.py            # 真调模型（720 次 Agent 运行 + 240 次评委调用）
    python examples/u19_traffic.py --replay
"""
import json
import random
import re
from concurrent.futures import ThreadPoolExecutor

from _llm import chat, replay_or_run
from mini_agent import run_agent
from mini_eval import CASES, KEY_TOOLS, SYSTEM, TOOLS, make_execute
from mini_world import verdict

BATCHES, PER_BATCH, CHANGE_AT = 12, 20, 7
JUDGE = "qwen-max"
BY_ID = {c["id"]: c for c in CASES}
TIMEOUT = json.dumps({"error": "下游服务超时（504），请稍后重试"}, ensure_ascii=False)


def sessions():
    rng = random.Random(19)
    out = []
    for b in range(1, BATCHES + 1):
        for _ in range(PER_BATCH):
            out.append({"id": f"S{len(out) + 1:03d}", "batch": b, "phase": "normal" if b < CHANGE_AT else "degraded",
                        "case": rng.choice(CASES)["id"]})
    return out


def execute_for(case, phase):
    base, n = make_execute(case), {"err": 0}

    def ex(name, args):
        if phase == "degraded" and name == "query_error_log" and args.get("instance") == case["instance"]:
            n["err"] += 1
            if n["err"] == 1:
                return TIMEOUT
        return base(name, args)
    return ex


def one(s, seed, full=True):
    case = BY_ID[s["case"]]
    ex, log = execute_for(case, s["phase"]), []

    def recorded(name, args):
        out = ex(name, args)
        log.append({"name": name, "ok": not out.startswith('{"error"'), "result": out})
        return out

    a = run_agent(case["question"], SYSTEM, TOOLS, recorded, max_turns=10, seed=seed)
    pred = verdict(a["answer"])
    if not full:
        return pred
    return {"calls": log, "answer": a["answer"] or "", "pred": pred, "turns": len(a["trace"]), "seconds": a["seconds"],
            "tokens": sum(t["prompt_tokens"] + t["completion_tokens"] for t in a["trace"])}


JUDGE_PROMPT = """下面是一个数据库值班 Agent 的一次排查：它调用工具拿到的全部结果，以及它最后的结论。只判断一件事：结论里的根因，有没有被这些工具结果直接支持？

规则：
1. 只看下面的工具结果和结论，不要用你自己对这次故障的猜测。
2. 工具结果里能直接看到支持这个根因的数据（指标数字、日志内容），算支持。
3. 只是“可能”“推测”，或者关键的数据源调用失败（超时、报错）后没有重试成功、结论又依赖它，算不支持。

先用两三句话说理由，最后一行只写：判定: 支持 / 不支持 / 无法判断

【工具结果】
{calls}

【结论】
{answer}"""


def judge(rec):
    calls = "\n".join(f"{i}. {c['name']} → {c['result']}" for i, c in enumerate(rec["calls"], 1)) or "（没有调用任何工具）"
    r = chat([{"role": "user", "content": JUDGE_PROMPT.format(calls=calls, answer=rec["answer"][-800:])}], model=JUDGE, seed=0)
    return r["text"]


def judge_verdict(text):
    m = re.findall(r"判定[\s:：#*\-]*(不支持|支持|无法判断)", text or "")
    return m[-1] if m else None


def run():
    ss = sessions()
    with ThreadPoolExecutor(max_workers=8) as pool:
        main = list(pool.map(lambda s: one(s, int(s["id"][1:])), ss))
        reruns = list(pool.map(lambda j: one(ss[j[0]], 1000 * j[1] + j[0], full=False),
                               [(i, k) for i in range(len(ss)) for k in (1, 2)]))
        judged = list(pool.map(judge, main))
    for i, (s, m) in enumerate(zip(ss, main)):
        s.update(m)
        s["reruns"] = reruns[2 * i: 2 * i + 2]
        s["judge"] = judged[i]
    return {"judge_model": JUDGE, "sessions": ss}


if __name__ == "__main__":
    r = replay_or_run("u19_traffic", run)
    for ph in ("normal", "degraded"):
        xs = [s for s in r["sessions"] if s["phase"] == ph]
        ok = sum(s["pred"] == BY_ID[s["case"]]["cause"] for s in xs)
        print(f"{ph:<9} {len(xs)} 个会话，答对 {ok}（{ok / len(xs):.0%}），评委判“不支持” "
              f"{sum(judge_verdict(s['judge']) == '不支持' for s in xs)}")
    print(f"\n模型 {r['_meta']['model']}，评委 {r['judge_model']}，{r['_meta']['date']} 实测；分析见 u19_monitor.py")
