"""单元十五 · 录下一批运行，供不同的打分器去判。

在单元十三的 Agent 上加一个要求：查出根因后，用 send_message 把结论同步到 #db-oncall，再回复用户。
两个版本，各在迷你评测集的 20 条用例上跑 3 遍：
  A  原样
  B  系统提示词再加一句：下结论之前，把四个数据源都查一遍
每次运行录下完整的回答、每一次工具调用（名字、参数、成功与否）、token 和耗时。
这里不打分：u15_graders.py 读录下的结果，用几种打分器重新判。

    python examples/u15_run.py            # 真调模型（120 次运行，约 600 次调用）
    python examples/u15_run.py --replay   # 只看汇总
"""
import json
from concurrent.futures import ThreadPoolExecutor

from _llm import replay_or_run
from mini_agent import run_agent
from mini_eval import CASES, SYSTEM, TOOLS, make_execute

RUNS = 3
SEND = {"type": "function", "function": {
    "name": "send_message", "description": "在 IM 里给一个频道发一条消息（用于同步结论、通知相关人）",
    "parameters": {"type": "object", "properties": {"channel": {"type": "string", "description": "频道名，以 # 开头"},
                                                    "text": {"type": "string"}}, "required": ["channel", "text"]}}}
SYNC = "。查出根因后，先用 send_message 把结论（根因 ID 和一句依据）同步到 #db-oncall，再回复用户"
VERSIONS = {
    "A": SYSTEM + SYNC,
    "B": SYSTEM + SYNC + "。下结论之前，把监控指标、慢查询日志、错误日志、网络检查四个数据源都查一遍",
}


def one(version, case, k):
    log, ex = [], make_execute(case)

    def recorded(name, args):
        out = json.dumps({"ok": True, "message_id": f"m{len(log)}"}) if name == "send_message" else ex(name, args)
        log.append({"name": name, "args": args, "ok": not out.startswith('{"error"')})
        return out

    a = run_agent(case["question"], VERSIONS[version], TOOLS + [SEND], recorded, max_turns=10, seed=k)
    return {"version": version, "case": case["id"], "k": k, "stop": a["stop"], "answer": a["answer"] or "",
            "calls": log, "turns": len(a["trace"]), "seconds": a["seconds"],
            "tokens": sum(t["prompt_tokens"] + t["completion_tokens"] for t in a["trace"])}


def run():
    jobs = [(v, c, k) for v in VERSIONS for c in CASES for k in range(RUNS)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        runs = list(pool.map(lambda j: one(*j), jobs))
    return {"systems": VERSIONS, "runs": runs}


if __name__ == "__main__":
    r = replay_or_run("u15_run", run)
    for v in VERSIONS:
        rs = [x for x in r["runs"] if x["version"] == v]
        print(f"版本 {v}：{len(rs)} 次运行，平均 {sum(x['tokens'] for x in rs) / len(rs):,.0f} token，"
              f"平均调工具 {sum(len(x['calls']) for x in rs) / len(rs):.1f} 次")
    print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测；打分见 u15_graders.py")
