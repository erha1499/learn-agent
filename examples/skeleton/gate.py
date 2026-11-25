"""发布门禁：候选版本和线上版本在同一套评测集上各跑几遍（单元十三、十五、十七、二十）。

    0. 指纹没变（只改了运维参数）：行为不会变，不用跑评测，直接过
    1. 底线：答对率、每次 token、耗时 p90 各有一条不管线上怎样都不能破的线，破了就不过
    2. 回归题：线上版本每遍都做对的题，候选版本不能变成大多数时候做错（单元十三）
    3. 和线上版本配对比较答错率：区间整个在 0 以上（显著变差）就不过；没显著但多错了 5 个点以上，要多跑几遍再定（单元十七）
    4. 目标：单元二十记分卡上的门槛，没达到不挡发布，但要报出来
    另外：没跑完的任务（服务出错、超时）单独统计，不当成答错；有这样的任务，先查原因、重跑，再下结论

第一版把目标也当成了挡发布的门槛（strict_targets=True）：线上版本自己的答错率就超过目标，
结果连行为完全不变的改动都过不去。单元二十二讲了这个教训。
"""
import math
import statistics as st

FLOORS = {"right_min": 0.80, "tokens_max": 6000, "p90_seconds_max": 60}
TARGETS = {"right_min": 0.85, "wrong_max": 0.10}


def summarize(runs):
    """runs: [{case, outcome: right/wrong/unknown, tokens, seconds}]"""
    n = len(runs)
    secs = sorted(r["seconds"] for r in runs)
    return {"n": n, "right": sum(r["outcome"] == "right" for r in runs) / n, "wrong": sum(r["outcome"] == "wrong" for r in runs) / n,
            "unknown": sum(r["outcome"] == "unknown" for r in runs) / n, "tokens": st.mean(r["tokens"] for r in runs),
            "p90_seconds": secs[int(.9 * n) - 1], "calls": st.mean(r.get("calls", 0) for r in runs),
            "unfinished": sum(r.get("status", "done") != "done" for r in runs)}


def per_case(runs, key):
    d = {}
    for r in runs:
        d.setdefault(r["case"], []).append(r["outcome"] == key)
    return {c: st.mean(v) for c, v in d.items()}


def gate(base_runs, cand_runs, same_fingerprint=False, floors=FLOORS, targets=TARGETS, strict_targets=False):
    if same_fingerprint:
        return {"decision": "通过", "reasons": ["指纹没变，行为不变，跳过评测"]}
    s, reasons, fail, more = summarize(cand_runs), [], False, False
    for ok, msg in ((s["right"] >= floors["right_min"], f"答对率 {s['right']:.0%}（底线 ≥ {floors['right_min']:.0%}）"),
                    (s["tokens"] <= floors["tokens_max"], f"每次 {s['tokens']:,.0f} token（底线 ≤ {floors['tokens_max']:,}）"),
                    (s["p90_seconds"] <= floors["p90_seconds_max"], f"耗时 p90 {s['p90_seconds']:.1f} 秒（底线 ≤ {floors['p90_seconds_max']}）")):
        if not ok:
            fail = True
            reasons.append("破了底线：" + msg)
    for ok, msg in ((s["right"] >= targets["right_min"], f"答对率 {s['right']:.0%}（目标 ≥ {targets['right_min']:.0%}）"),
                    (s["wrong"] <= targets["wrong_max"], f"答错率 {s['wrong']:.0%}（目标 ≤ {targets['wrong_max']:.0%}）")):
        if not ok:
            if strict_targets:
                fail = True
            reasons.append(("没达到目标（第一版规则会挡下）：" if strict_targets else "没达到目标（不挡发布）：") + msg)
    if s["unfinished"]:
        more = True
        reasons.append(f"有 {s['unfinished']} 个任务没跑完：先查原因、重跑，不当成答错")
    b_right, c_right = per_case(base_runs, "right"), per_case(cand_runs, "right")
    broke = [c for c, v in b_right.items() if v == 1 and c_right.get(c, 0) < 0.5]
    if broke:
        fail = True
        reasons.append(f"回归题做坏了：{', '.join(sorted(broke))}")
    bw, cw = per_case(base_runs, "wrong"), per_case(cand_runs, "wrong")
    d = [cw[c] - bw[c] for c in bw]
    mean, half = st.mean(d), 1.96 * st.stdev(d) / math.sqrt(len(d))
    cmp_ = f"答错率比线上 {mean * 100:+.1f} ± {half * 100:.1f} 个点"
    if mean - half > 0:
        fail = True
        reasons.append("显著变差：" + cmp_)
    elif mean > 0.05:
        more = True
        reasons.append("可能变差、还不确定：" + cmp_)
    else:
        reasons.append(cmp_)
    return {"decision": "不过" if fail else ("多跑几遍再定" if more else "通过"), "reasons": reasons, "summary": s}
