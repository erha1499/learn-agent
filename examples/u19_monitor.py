"""单元十九 · 读 u19_traffic.py 录下的 240 个会话，不调模型。

  一、真实答对率（线上看不到，只在模拟里知道）
  二、不用标准答案的信号：各标记了多少会话，抓到多少答错的，标记里多少真错
  三、抽样：随机抽一批人工核对，估答对率；只核对被标记的会话，会把答对率估成多少
  四、按批次看监控：基础设施变更前后，哪些信号动了
随机数种子固定，结果可复现。

    python examples/u19_monitor.py
"""
import json
import math
import os
import random
import statistics as st

from mini_eval import CASES, KEY_TOOLS
from u19_traffic import CHANGE_AT, judge_verdict

R = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "u19_traffic.json"), encoding="utf-8"))
SS = R["sessions"]
CAUSE = {c["id"]: c["cause"] for c in CASES}
LEVEL = {c["id"]: c["level"] for c in CASES}
rng = random.Random(0)


def unrecovered(calls):
    """有一次工具报错，之后同一个工具再也没有成功过。"""
    return any(not c["ok"] and not any(d["ok"] and d["name"] == c["name"] for d in calls[i + 1:])
               for i, c in enumerate(calls))


for s in SS:
    s["correct"] = s["pred"] == CAUSE[s["case"]]
    ok_tools = {c["name"] for c in s["calls"] if c["ok"]}
    s["sig"] = {
        "没给结论": s["pred"] is None,
        "结论缺关键证据": s["pred"] is not None and not (KEY_TOOLS.get(s["pred"], set()) & ok_tools),
        "报错没重试成功": unrecovered(s["calls"]),
        "工具调得太少": len(s["calls"]) < 2,
        "评委判不支持": judge_verdict(s["judge"]) != "支持",
        "再跑两遍不一致": len({s["pred"], *s["reruns"]}) > 1,
    }
    s["sig"]["代码检查（没给结论、太少、缺证据）"] = any(s["sig"][k] for k in ("没给结论", "结论缺关键证据", "工具调得太少"))
    s["sig"]["代码检查 + 评委"] = s["sig"]["代码检查（没给结论、太少、缺证据）"] or s["sig"]["评委判不支持"]
    s["sig"]["代码检查 + 评委 + 一致性"] = s["sig"]["代码检查 + 评委"] or s["sig"]["再跑两遍不一致"]
    s["sig"]["再加上报错没重试成功"] = s["sig"]["代码检查 + 评委 + 一致性"] or s["sig"]["报错没重试成功"]

PH = {"normal": "变更前", "degraded": "变更后"}
print(f"{len(SS)} 个会话，{max(s['batch'] for s in SS)} 批；第 {CHANGE_AT} 批起错误日志第一次调用超时\n")

print("=== 一、真实答对率（线上看不到）")
for ph, name in PH.items():
    xs = [s for s in SS if s["phase"] == ph]
    print(f"  {name}：{sum(s['correct'] for s in xs)}/{len(xs)}（{st.mean(s['correct'] for s in xs):.1%}）")
wrong = [s for s in SS if not s["correct"]]
print(f"  答错的 {len(wrong)} 个会话来自：" + "，".join(f"{c}×{n}" for c, n in sorted(
    {c: sum(s['case'] == c for s in wrong) for c in {s['case'] for s in wrong}}.items(), key=lambda x: -x[1])))

print("\n=== 二、不用标准答案的信号（全部 240 个会话；答错的分成 C15 注入那条和其他）")
inj = [s for s in wrong if s["case"] == "C15"]
other = [s for s in wrong if s["case"] != "C15"]
print(f"  {'信号':<22}{'标记了':>10}{'抓到答错':>10}{'其中 C15':>8}{'其中其他':>8}{'标记里真错的':>10}")
for k in SS[0]["sig"]:
    flagged = [s for s in SS if s["sig"][k]]
    hit = sum(not s["correct"] for s in flagged)
    prec = f"{hit / len(flagged):.0%}" if flagged else "—"
    print(f"  {k:<22}{len(flagged):>5}（{len(flagged) / len(SS):.0%}）{hit:>6}/{len(wrong)}"
          f"{sum(s['sig'][k] for s in inj):>6}/{len(inj)}{sum(s['sig'][k] for s in other):>6}/{len(other)}{prec:>10}")
miss = [s for s in wrong if not s["sig"]["代码检查 + 评委 + 一致性"]]
print(f"  代码检查 + 评委 + 一致性 都没标记出来的答错：{len(miss)} 个，" +
      "，".join(f"{c}×{n}" for c, n in sorted({c: sum(s['case'] == c for s in miss) for c in {s['case'] for s in miss}}.items(), key=lambda x: -x[1])) +
      "；答成 " + "，".join(f"{p}×{n}" for p, n in sorted({p: sum(s['pred'] == p for s in miss) for p in {s['pred'] for s in miss}}.items(), key=lambda x: -x[1])))
by_phase = {ph: [s for s in SS if s["phase"] == ph] for ph in PH}
for ph, xs in by_phase.items():
    f = [s for s in xs if s["sig"]["报错没重试成功"]]
    print(f"  {PH[ph]}：“报错没重试成功”标记 {len(f)}/{len(xs)}，其中真错 {sum(not s['correct'] for s in f)}")
jt = [s for s in SS if judge_verdict(s["judge"]) is None]
print(f"  评委没按格式给判定：{len(jt)} 次（算作“不支持”）")

print("\n=== 三、抽样估答对率（用真实标签模拟人工核对，重复 5,000 次）")
for ph, xs in by_phase.items():
    truth = st.mean(s["correct"] for s in xs)
    for n in (20, 40):
        est, cover = [], 0
        for _ in range(5000):
            smp = rng.sample(xs, n)
            p = st.mean(s["correct"] for s in smp)
            half = 1.96 * math.sqrt(max(p * (1 - p), 1e-9) / n)
            est.append(p)
            cover += p - half <= truth <= p + half
        est.sort()
        print(f"  {PH[ph]}  真实 {truth:.1%}；随机抽 {n} 个：90% 的估计落在 {est[250]:.0%} ～ {est[4749]:.0%}，"
              f"“± 1.96 标准误”覆盖真实值 {cover / 5000:.0%}")
    flagged = [s for s in xs if s["sig"]["代码检查 + 评委 + 一致性"]]
    print(f"    只核对被标记的 {len(flagged)} 个：答对率看起来是 {st.mean(s['correct'] for s in flagged):.0%}；"
          f"没被标记的 {len(xs) - len(flagged)} 个里答对 {st.mean(s['correct'] for s in xs if not s['sig']['代码检查 + 评委 + 一致性']):.0%}")
hits = 0
for _ in range(5000):
    a = [s["correct"] for s in rng.sample(by_phase["normal"], 40)]
    b = [s["correct"] for s in rng.sample(by_phase["degraded"], 40)]
    d = st.mean(a) - st.mean(b)
    se = math.sqrt(st.pvariance(a) / 40 + st.pvariance(b) / 40)
    hits += d - 1.96 * se > 0
print(f"  变更前后各随机抽 40 个核对，看出“变更后变差”（差值区间整个在 0 以上）的比例：{hits / 5000:.0%}")
print("  流量的组成也在变：")
for ph, xs in by_phase.items():
    rest = [s for s in xs if s["case"] != "C15"]
    print(f"    {PH[ph]}：C15 出现 {len(xs) - len(rest)} 次；去掉 C15 答对 {sum(s['correct'] for s in rest)}/{len(rest)}（{st.mean(s['correct'] for s in rest):.1%}）")
pairs = []
for c in sorted(CAUSE):
    a = [s["correct"] for s in by_phase["normal"] if s["case"] == c]
    b = [s["correct"] for s in by_phase["degraded"] if s["case"] == c]
    if a and b:
        pairs.append(st.mean(b) - st.mean(a))
print(f"    按用例配对（{len(pairs)} 条用例在前后都出现过）：变更后减变更前 {st.mean(pairs) * 100:+.1f} ± "
      f"{1.96 * st.stdev(pairs) / math.sqrt(len(pairs)) * 100:.1f} 个点")
for c in sorted(CAUSE):
    a = [s["correct"] for s in by_phase["normal"] if s["case"] == c]
    b = [s["correct"] for s in by_phase["degraded"] if s["case"] == c]
    if a and b and st.mean(a) != st.mean(b):
        wrong_preds = [s["pred"] for s in by_phase["degraded"] if s["case"] == c and not s["correct"]]
        print(f"      {c} {LEVEL[c]:<8} {CAUSE[c]:<15} 变更前 {sum(a)}/{len(a)}  变更后 {sum(b)}/{len(b)}  变更后答成 {wrong_preds}")

print("\n=== 四、按批次看监控（每批 20 个会话）")
print(f"  {'批':>2}  {'真实答对':>6}  {'工具报错率':>8}  {'代码检查标记':>8}  {'评委不支持':>8}  {'不一致':>6}  {'平均调工具':>8}  {'平均 token':>8}")
for b in sorted({s["batch"] for s in SS}):
    xs = [s for s in SS if s["batch"] == b]
    calls = [c for s in xs for c in s["calls"]]
    print(f"  {b:>2}  {st.mean(s['correct'] for s in xs):>8.0%}  {sum(not c['ok'] for c in calls) / len(calls):>10.0%}"
          f"  {st.mean(s['sig']['代码检查（没给结论、太少、缺证据）'] for s in xs):>12.0%}  {st.mean(s['sig']['评委判不支持'] for s in xs):>10.0%}"
          f"  {st.mean(s['sig']['再跑两遍不一致'] for s in xs):>8.0%}  {st.mean(len(s['calls']) for s in xs):>10.1f}"
          f"  {st.mean(s['tokens'] for s in xs):>10,.0f}")
print("  变更后减变更前（按会话算，± 1.96 标准误）：")
metrics = {"真实答对率": lambda s: s["correct"], "工具报错率（每个会话）": lambda s: sum(not c["ok"] for c in s["calls"]) / max(1, len(s["calls"])),
           "代码检查标记率": lambda s: s["sig"]["代码检查（没给结论、太少、缺证据）"], "评委判不支持": lambda s: s["sig"]["评委判不支持"],
           "再跑不一致": lambda s: s["sig"]["再跑两遍不一致"], "调工具次数": lambda s: len(s["calls"]), "token": lambda s: s["tokens"],
           "耗时（秒）": lambda s: s["seconds"]}
for name, f in metrics.items():
    a, b = [f(s) for s in by_phase["normal"]], [f(s) for s in by_phase["degraded"]]
    d = st.mean(b) - st.mean(a)
    se = math.sqrt(st.variance(a) / len(a) + st.variance(b) / len(b))
    rate = name not in ("调工具次数", "token", "耗时（秒）")
    fmt = (lambda x: f"{x * 100:+.1f} 个点") if rate else (lambda x: f"{x:+,.1f}")
    print(f"    {name:<14} {st.mean(a) if not rate else st.mean(a) * 100:>8.1f}{'%' if rate else ''} → "
          f"{st.mean(b) if not rate else st.mean(b) * 100:.1f}{'%' if rate else ''}  差 {fmt(d)} ± {fmt(1.96 * se)[1:]}"
          f"{'  ← 显著' if abs(d) > 1.96 * se else ''}")
jtok = st.mean(len(s["judge"]) for s in SS)
print(f"\n评委回复平均 {jtok:.0f} 字；模型 {R['_meta']['model']}，评委 {R['judge_model']}，{R['_meta']['date']} 实测")
