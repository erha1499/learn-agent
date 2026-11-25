"""单元十五 · 同一批运行，换打分器看分数。不调模型，只读 u15_run.py 录下的结果。

打分器（每个都是一个小函数，输入一次运行和它的用例，输出对或错）：
  结论·严格      回答最后一个“根因: <ID>”等于标准答案
  结论·宽松      回答里任何地方出现了标准答案的编号或中文关键词
  关键证据       成功调用过能证明这个根因的工具（单元十三）
  同步·看说法    回答里写了 send_message，或者说自己已经同步、发送、通知了
  同步·看记录    工具记录里真有一条发到 #db-oncall 的消息
  同步·发对了    发到 #db-oncall 的消息里写的是正确的根因编号

    python examples/u15_graders.py
"""
import json
import os
import re
from statistics import median

from mini_eval import CASES, KEY_TOOLS
from mini_world import verdict

CASE = {c["id"]: c for c in CASES}
KEYWORDS = {"MAX_CONNECTIONS": ["连接数"], "SLOW_SQL": ["慢 SQL", "慢SQL", "慢查询"], "LOCK_WAIT": ["锁等待"],
            "DISK_FULL": ["磁盘"], "NETWORK": ["网络"]}


def sends(run):
    return [c for c in run["calls"] if c["name"] == "send_message" and isinstance(c["args"], dict)
            and str(c["args"].get("channel", "")).strip().lower() == "#db-oncall"]


def outcome_strict(run, case):
    return verdict(run["answer"]) == case["cause"]


def outcome_loose(run, case):
    t = run["answer"]
    return case["cause"] in t or any(k in t for k in KEYWORDS[case["cause"]])


def key_evidence(run, case):
    return any(c["ok"] and c["name"] in KEY_TOOLS[case["cause"]] for c in run["calls"])


def synced_claim(run, case):
    return bool(re.search(r"send_message|同步(至|到)\s*#?db-oncall|已(经)?(同步|发送|通知|触发)", run["answer"]))


def synced_state(run, case):
    return bool(sends(run))


def synced_correct(run, case):
    return any(case["cause"] in str(c["args"].get("text", "")) for c in sends(run))


def all_pass(run, case):
    return outcome_strict(run, case) and key_evidence(run, case) and synced_correct(run, case)


def weighted(run, case):
    return 0.5 * outcome_strict(run, case) + 0.25 * key_evidence(run, case) + 0.25 * synced_correct(run, case)


GRADERS = [("结论·严格", outcome_strict), ("结论·宽松", outcome_loose), ("关键证据", key_evidence),
           ("同步·看说法", synced_claim), ("同步·看记录", synced_state), ("同步·发对了", synced_correct),
           ("全部通过", all_pass)]


def load():
    path = os.path.join(os.path.dirname(__file__), "output", "u15_run.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def pct(xs):
    return f"{sum(xs)}/{len(xs)}"


def main():
    r = load()
    runs = {v: [x for x in r["runs"] if x["version"] == v] for v in r["systems"]}

    print("=== 一、版本 A 的 60 次运行，七个打分器各判对几次")
    for name, g in GRADERS:
        print(f"  {name:<8} {pct([g(x, CASE[x['case']]) for x in runs['A']])}")

    a = runs["A"]
    loose_only = [x for x in a if outcome_loose(x, CASE[x["case"]]) and not outcome_strict(x, CASE[x["case"]])]
    strict_only = [x for x in a if outcome_strict(x, CASE[x["case"]]) and not outcome_loose(x, CASE[x["case"]])]
    print(f"\n=== 二、严格和宽松不一致的运行：宽松判对、严格判错 {len(loose_only)} 次；严格判对、宽松判错 {len(strict_only)} 次")
    for x in loose_only:
        c = CASE[x["case"]]
        print(f"  {x['case']} 第{x['k'] + 1}遍  真实 {c['cause']}  严格取到 {verdict(x['answer'])}  回答结尾：{x['answer'][-110:]!r}")

    print("\n=== 三、同步：回答里的说法 vs 工具记录")
    for v, rs in runs.items():
        cells = []
        for claim in (True, False):
            for state in (True, False):
                n = sum(1 for x in rs if synced_claim(x, CASE[x["case"]]) == claim and synced_state(x, CASE[x["case"]]) == state)
                cells.append(f"说了{'是' if claim else '否'}/发了{'是' if state else '否'} {n}")
        print(f"  {v}：" + "，".join(cells))
    for x in runs["B"]:
        if synced_claim(x, CASE[x["case"]]) and not synced_state(x, CASE[x["case"]]):
            line = next(l for l in x["answer"].splitlines() if re.search(r"send_message|同步|已触发", l))
            print(f"    B {x['case']} 第{x['k'] + 1}遍  回答里写：{line.strip()[:90]}")
    bad = [x for x in a if synced_state(x, CASE[x["case"]]) and not synced_correct(x, CASE[x["case"]])]
    print(f"  真发了、但消息里的根因不对：{len(bad)}")
    for x in bad[:5]:
        print(f"    {x['case']} 第{x['k'] + 1}遍  消息：{[c['args'].get('text', '')[:80] for c in sends(x)]}")

    print("\n=== 四、A、B 两个版本，换个指标看谁好")
    rows = [("结论·严格", outcome_strict), ("关键证据", key_evidence), ("同步·发对了", synced_correct),
            ("全部通过", all_pass)]
    for name, g in rows:
        print(f"  {name:<8} " + "  ".join(f"{v} {pct([g(x, CASE[x['case']]) for x in rs])}" for v, rs in runs.items()))
    for v, rs in runs.items():
        w = sum(weighted(x, CASE[x["case"]]) for x in rs) / len(rs)
        p3 = sum(all(all_pass(x, CASE[cid]) for x in rs if x["case"] == cid) for cid in CASE) / len(CASE)
        tok = [x["tokens"] for x in rs]
        sec = sorted(x["seconds"] for x in rs)
        passed = sum(all_pass(x, CASE[x["case"]]) for x in rs)
        print(f"  {v}：加权分 {w:.1%}，全部通过的 pass^3 {p3:.0%}，每次运行 {sum(tok) / len(tok):,.0f} token、"
              f"调工具 {sum(len(x['calls']) for x in rs) / len(rs):.1f} 次、耗时中位数 {median(sec):.1f} 秒（最慢 {sec[-1]:.1f} 秒），"
              f"每次“全部通过”花 {sum(tok) / max(passed, 1):,.0f} token")

    print("\n=== 五、按难度看“全部通过”")
    for level in ("plain", "distract", "mislead", "flaky"):
        print(f"  {level:<9}" + "  ".join(
            f"{v} {pct([all_pass(x, CASE[x['case']]) for x in rs if CASE[x['case']]['level'] == level])}" for v, rs in runs.items()))

    print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")


if __name__ == "__main__":
    main()
