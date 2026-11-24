"""单元十四 · 评测集要多大？用单元十三录下的真实运行做模拟，不调模型。

把单元十三评测集 20 条用例各自 3 遍的平均正确率，当作“这类用例的真实答对概率”的总体（examples/output/u13_run.json）。
  A. 估计会晃多少：从总体里有放回地抽 n 条用例、每条跑 1 遍，算答对率；重复 1 万次，看 90% 的结果落在多宽的范围里。
  B. 看不看得出提升：假设新版本 B 真的比 A 好 δ 个点（提升集中在还没做稳的用例上），
     两个版本在同一批 n 条用例上各跑 1 遍，数“B 的答对率高于 A”和“B 反而低于 A”各占多少。
随机数种子固定，结果可复现。

    python examples/u14_size.py
"""
import json
import os
import random

ROOT = os.path.dirname(os.path.abspath(__file__))
cases = json.load(open(os.path.join(ROOT, "output", "u13_run.json"), encoding="utf-8"))["cases"]
P = [sum(r["correct"] for r in c["runs"]) / len(c["runs"]) for c in cases]
MEAN = sum(P) / len(P)
rng = random.Random(0)
SIMS = 10000


def spread(n):
    est = sorted(sum(rng.random() < rng.choice(P) for _ in range(n)) / n for _ in range(SIMS))
    return est[int(.05 * SIMS)], est[int(.95 * SIMS)]


def better(p, delta):
    return min(1.0, p + delta * (1 - p) / (1 - MEAN))      # 平均提升 delta，越没做稳的用例提升越多


def compare(n, delta, runs=1):
    up = down = 0
    for _ in range(SIMS):
        idx = [rng.randrange(len(P)) for _ in range(n)]
        a = sum(rng.random() < P[i] for i in idx for _ in range(runs))
        b = sum(rng.random() < better(P[i], delta) for i in idx for _ in range(runs))
        up += b > a
        down += b < a
    return up / SIMS, down / SIMS


print(f"总体：{len(P)} 条用例，平均答对率 {MEAN:.1%}\n")
print("=== A. 只跑一遍时，答对率的估计会落在多宽的范围（90% 的情况）")
for n in (10, 30, 100, 300):
    lo, hi = spread(n)
    print(f"  {n:>4} 条：{lo:.1%} ～ {hi:.1%}（宽 {hi - lo:.1%}）")
print("\n=== B. B 真的比 A 好 δ 个点，在同一批用例上各跑一遍：看到 B 更高 / 看到 B 反而更低")
for delta in (0.05, 0.10):
    for n in (10, 30, 100, 300):
        up, down = compare(n, delta)
        print(f"  δ = {delta:.0%}，{n:>4} 条：B 更高 {up:.0%}，B 反而更低 {down:.0%}")
print("\n=== 每条用例跑 3 遍（30 条）")
for delta in (0.05, 0.10):
    up, down = compare(30, delta, runs=3)
    print(f"  δ = {delta:.0%}：B 更高 {up:.0%}，B 反而更低 {down:.0%}")
