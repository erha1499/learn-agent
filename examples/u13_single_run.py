"""单元十三 · 只跑一遍的评测，结果能差多少？

把每条用例 3 遍的平均正确率，当成它“真实的答对概率”，模拟“把这 20 条只跑一遍”1 万次，看答对率会落在什么范围。
读 u13_run.py 录下的结果，不调模型，随机数种子固定：
    python examples/u13_single_run.py
"""
import json
import os
import random

ROOT = os.path.dirname(os.path.abspath(__file__))
cases = json.load(open(os.path.join(ROOT, "output", "u13_run.json"), encoding="utf-8"))["cases"]
p = [sum(x["correct"] for x in c["runs"]) / len(c["runs"]) for c in cases]
rng = random.Random(0)
sims = sorted(sum(rng.random() < q for q in p) / len(p) for _ in range(10000))
true = sum(p) / len(p)
pct = lambda q: sims[int(q * (len(sims) - 1))]  # noqa: E731
print(f"每条用例的答对概率取 3 遍的平均，整体期望答对率 = {true:.1%}")
print(f"只跑一遍，模拟 10000 次：最低 {sims[0]:.1%}，最高 {sims[-1]:.1%}；中间 90% 落在 {pct(0.05):.1%} ～ {pct(0.95):.1%}")
for d in (0.05, 0.10):
    worse = sum(s <= true - d for s in sims) / len(sims)
    print(f"  同一个版本、什么都没改，只跑一遍就比期望低 {d * 100:.0f} 个点以上的概率：{worse:.1%}")
