"""单元十七 · 结论能不能信：读 u17_run.py 录下的 400 次运行做统计，不调模型。

  一、两个版本每一遍的答对数：只跑一遍，B 比 A 好还是差？
  二、给一个分数加误差范围：把 200 次运行当成 200 个独立样本，和按用例算，误差差多少
  三、比两个版本：不配对和配对；“这 20 条上是不是运行的随机性”和“换一批用例还在不在”是两个问题
  四、少跑几遍会怎样：从录下的 10 遍里随机抽 k 遍，看两种区间各多宽；要多少条用例才看得出 5 个点
  五、A/A：同一个版本的两批运行，什么都没改，拆成 15 个比较能“看出”什么
  六、挑最好的一遍报：会比真实水平高多少
随机数种子固定，结果可复现。

    python examples/u17_stats.py
"""
import json
import math
import os
import random
import statistics as st

ROOT = os.path.dirname(os.path.abspath(__file__))
R = json.load(open(os.path.join(ROOT, "output", "u17_run.json"), encoding="utf-8"))
RUNS = R["runs"]
CASES = sorted({x["case"] for x in RUNS})
LEVEL = {x["case"]: x["level"] for x in RUNS}
LEVELS = ("plain", "distract", "mislead", "flaky")
K = max(x["k"] for x in RUNS) + 1
Z = 1.96
T = {5: 2.776, 20: 2.093}          # t 分布 95% 双侧临界值：自由度 4、19（用例数 5、20）
rng = random.Random(0)

V = {}                              # V[版本][指标][用例] = 按 k 排好的 10 个值
for x in RUNS:
    for m in ("correct", "key_evidence", "tokens", "calls"):
        V.setdefault(x["version"], {}).setdefault(m, {}).setdefault(x["case"], [None] * K)[x["k"]] = float(x[m])


def case_means(ver, m, ks=None, cases=CASES):
    return [st.mean(V[ver][m][c][k] for k in (ks if ks is not None else range(K))) for c in cases]


def se(xs):
    return st.stdev(xs) / math.sqrt(len(xs)) if len(xs) > 1 else 0.0


def pct(x):
    return f"{x * 100:+.1f}" if x < 0 or x > 0 else "0.0"


def ci(m, s, z=Z):
    return f"{m:.1%} ± {z * s:.1%}（{m - z * s:.1%} ～ {m + z * s:.1%}）"


def dci(m, s, z=Z):
    return f"{pct(m)} ± {z * s * 100:.1f} 个点（{pct(m - z * s)} ～ {pct(m + z * s)}）"


def boot(xs, n=10000):
    est = sorted(st.mean(rng.choice(xs) for _ in xs) for _ in range(n))
    return est[int(.025 * n)], est[int(.975 * n)]


print(f"{len(CASES)} 条用例 × {K} 遍 × 2 个版本 = {len(RUNS)} 次运行\n")

print("=== 一、每一遍的答对数（20 条用例）")
diffs = []
for k in range(K):
    a, b = (sum(V[v]["correct"][c][k] for c in CASES) for v in "AB")
    diffs.append(b - a)
    print(f"  第 {k + 1:>2} 遍  A {a:.0f}  B {b:.0f}  B−A {b - a:+.0f}")
print(f"  B 更高 {sum(d > 0 for d in diffs)} 遍，打平 {sum(d == 0 for d in diffs)} 遍，B 更低 {sum(d < 0 for d in diffs)} 遍")
for v in "AB":
    print(f"  {v} 合计 {sum(sum(V[v]['correct'][c]) for c in CASES):.0f}/{len(CASES) * K}")

print("\n=== 二、给答对率加 95% 置信区间")
for v in "AB":
    flat = [y for c in CASES for y in V[v]["correct"][c]]
    p = st.mean(flat)
    naive = math.sqrt(p * (1 - p) / len(flat))
    m = case_means(v, "correct")
    lo, hi = boot(m)
    print(f"  {v}  把 {len(flat)} 次运行当独立样本：{ci(p, naive)}")
    print(f"     按用例算（20 个用例平均值）：{ci(st.mean(m), se(m))}；标准误是前者的 {se(m) / naive:.1f} 倍")
    print(f"     对用例做自助抽样：{lo:.1%} ～ {hi:.1%}")
    within = st.mean(st.variance(V[v]["correct"][c]) for c in CASES)
    print(f"     用例之间的方差 {st.variance(m) - within / K:.3f}，同一用例跑多遍的方差 {within:.3f}"
          f"（10 遍平均后只剩 {within / K:.3f}）")
    print(f"     10 遍全对的用例 {sum(x == 1 for x in m)} 条，全错 {sum(x == 0 for x in m)} 条，时对时错 {sum(0 < x < 1 for x in m)} 条")

print("\n=== 三、B 比 A 好多少：不配对和配对")
for metric, name in (("correct", "答对率"), ("key_evidence", "拿到关键证据")):
    mA, mB = case_means("A", metric), case_means("B", metric)
    d = [b - a for a, b in zip(mA, mB)]
    unpaired = math.sqrt(se(mA) ** 2 + se(mB) ** 2)
    lo, hi = boot(d)
    print(f"  {name}：A {st.mean(mA):.1%}，B {st.mean(mB):.1%}；两版本按用例的相关系数 {st.correlation(mA, mB):.2f}")
    print(f"    不配对：{dci(st.mean(d), unpaired)}")
    print(f"    配对：  {dci(st.mean(d), se(d))}；自助抽样 {pct(lo)} ～ {pct(hi)}；配对的标准误是不配对的 {se(d) / unpaired:.2f}")
tA, tB = case_means("A", "tokens"), case_means("B", "tokens")
td = [b - a for a, b in zip(tA, tB)]
print(f"  每次运行的 token：A {st.mean(tA):,.0f}，B {st.mean(tB):,.0f}；配对差 {st.mean(td):+,.0f} ± {Z * se(td):,.0f}"
      f"（{st.mean(td) / st.mean(tA):+.0%}）")
cA, cB = case_means("A", "calls"), case_means("B", "calls")
print(f"  每次运行调工具：A {st.mean(cA):.2f} 次，B {st.mean(cB):.2f} 次")
print("  按难度拆开（答对率，配对，每组 5 条用例，用 t 分布临界值 2.776）：")
for lv in LEVELS:
    cs = [c for c in CASES if LEVEL[c] == lv]
    a, b = case_means("A", "correct", cases=cs), case_means("B", "correct", cases=cs)
    d = [y - x for x, y in zip(a, b)]
    print(f"    {lv:<8}  A {st.mean(a):.0%}  B {st.mean(b):.0%}  差 {dci(st.mean(d), se(d), T[5])}")
print("  两个版本答对率不一样的用例：")
for c in CASES:
    a, b = st.mean(V["A"]["correct"][c]), st.mean(V["B"]["correct"][c])
    if a != b:
        print(f"    {c} {LEVEL[c]:<8}  A {a * K:.0f}/{K}  B {b * K:.0f}/{K}")
mA, mB = case_means("A", "correct"), case_means("B", "correct")
obs = st.mean(mB) - st.mean(mA)
fixed = math.sqrt(sum(st.variance(V["A"]["correct"][c]) / K + st.variance(V["B"]["correct"][c]) / K for c in CASES)) / len(CASES)
print(f"  只问“这 20 条用例上的差距是不是运行的随机性”：只算同一用例跑多遍的波动，差值 {dci(obs, fixed)}")
hits = 0
for _ in range(10000):                 # 每条用例内部把 A、B 的 20 次运行打乱，重新分成两组 10 次
    tot = 0.0
    for c in CASES:
        pool = V["A"]["correct"][c] + V["B"]["correct"][c]
        rng.shuffle(pool)
        tot += st.mean(pool[K:]) - st.mean(pool[:K])
    hits += abs(tot / len(CASES)) >= abs(obs) - 1e-12
print(f"    置换检验（每条用例内部打乱 A、B 的运行，1 万次）：差距不小于 {pct(obs)} 个点的比例 {hits / 10000:.2%}")
rest = [c for c in CASES if c != "C15"]
print(f"  去掉 C15：A {st.mean(case_means('A', 'correct', cases=rest)):.1%}，B {st.mean(case_means('B', 'correct', cases=rest)):.1%}")

print("\n=== 四、只跑 k 遍会怎样（从录下的 10 遍里随机抽 k 遍，重复 5,000 次）")
for k in (1, 3, 5, 10):
    widths, aw, fw, seen, fseen, worse = [], [], [], 0, 0, 0
    sims = 1 if k == K else 5000
    for _ in range(sims):
        ka = {c: rng.sample(range(K), k) for c in CASES}
        kb = {c: rng.sample(range(K), k) for c in CASES}
        xa = {c: [V["A"]["correct"][c][j] for j in ka[c]] for c in CASES}
        xb = {c: [V["B"]["correct"][c][j] for j in kb[c]] for c in CASES}
        mA, mB = [st.mean(xa[c]) for c in CASES], [st.mean(xb[c]) for c in CASES]
        d = [b - a for a, b in zip(mA, mB)]
        md = st.mean(d)
        widths.append(Z * se(d))
        aw.append(Z * se(mA))
        seen += md - Z * se(d) > 0
        worse += md < 0
        if k > 1:                      # 只算同一用例跑多遍的波动（问题一）
            f = math.sqrt(sum(st.variance(xa[c]) / k + st.variance(xb[c]) / k for c in CASES)) / len(CASES)
            fw.append(Z * f)
            fseen += md - Z * f > 0
    fixed_txt = f"±{st.median(fw):.1%}，整个在 0 以上 {fseen / sims:.0%}" if k > 1 else "跑一遍算不出"
    print(f"  每条跑 {k:>2} 遍：A 答对率的区间 ±{st.median(aw):.1%}；B−A 只算运行波动的区间 {fixed_txt}；"
          f"按用例的区间 ±{st.median(widths):.1%}，整个在 0 以上 {seen / sims:.0%}；B 看起来反而更差 {worse / sims:.0%}")
mA, mB = case_means("A", "correct"), case_means("B", "correct")
sd_d = st.stdev([b - a for a, b in zip(mA, mB)])
sd_u = math.sqrt(st.variance(mA) + st.variance(mB))
print(f"  按这次 10 遍的波动估算：想以 80% 的把握看出 5 个点的差距，配对要 {((Z + 0.84) * sd_d / 0.05) ** 2:.0f} 条用例，"
      f"不配对要 {((Z + 0.84) * sd_u / 0.05) ** 2:.0f} 条")

print("\n=== 五、A/A：A 的 10 遍随机分成两批各 3 遍，什么都没改，比较 5 组 × 3 个指标 = 15 次（重复 2,000 次）")
groups = [("全部", CASES)] + [(lv, [c for c in CASES if LEVEL[c] == lv]) for lv in LEVELS]
maxgap, big, any_sig, sig_total, overall = [], 0, 0, 0, []
for it in range(2000):
    split = {c: rng.sample(range(K), 6) for c in CASES}
    gaps, sig = [], 0
    for gname, cs in groups:
        for metric in ("correct", "key_evidence", "tokens"):
            x = [st.mean(V["A"][metric][c][j] for j in split[c][:3]) for c in cs]
            y = [st.mean(V["A"][metric][c][j] for j in split[c][3:]) for c in cs]
            d = [b - a for a, b in zip(x, y)]
            md, s = st.mean(d), se(d)
            if metric == "tokens":
                md, s = md / st.mean(x), s / st.mean(x)
            else:
                gaps.append(abs(md))
            hit = abs(md) > T[len(cs)] * s if s > 0 else md != 0
            sig += hit
            if gname == "全部" and metric == "correct":
                overall.append(md)
    maxgap.append(max(gaps))
    big += max(gaps) >= 0.2
    any_sig += sig > 0
    sig_total += sig
overall.sort()
print(f"  全部用例的答对率，两批之差：90% 落在 {pct(overall[100])} ～ {pct(overall[1899])} 个点")
print(f"  10 个比率比较里差得最大的那个：中位数 {st.median(maxgap) * 100:.0f} 个点；有一个差到 20 个点以上的 {big / 2000:.0%}")
print(f"  每次比较“显著”的比例 {sig_total / 2000 / 15:.1%}；15 次里至少一次“显著”的 {any_sig / 2000:.0%}")

print("\n=== 六、跑几遍、挑最好的一遍报（A，单遍答对率）")
single = [st.mean(V["A"]["correct"][c][k] for c in CASES) for k in range(K)]
print(f"  10 遍的单遍答对率：{', '.join(f'{x:.0%}' for x in single)}；平均 {st.mean(single):.1%}")
for m in (3, 5):
    best = st.mean(max(rng.sample(single, m)) for _ in range(5000))
    print(f"  跑 {m} 遍挑最好的：平均报出 {best:.1%}，比 10 遍平均高 {(best - st.mean(single)) * 100:.1f} 个点")
print(f"\n模型 {R['_meta']['model']}，{R['_meta']['date']} 实测")
