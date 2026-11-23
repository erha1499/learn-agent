"""单元十 · 同一个版本跑 3 遍：结果稳不稳？pass@k 和 pass^k 是什么？

数据是 oncall-agent-mvp 的真实运行（v2.1，复刻集 30 条用例 × 3 遍），从评测平台导出在 data/oncall_v21_replica.json。
不调模型，直接跑：python examples/u10_repeats.py
"""
import json
import os
from math import comb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
snap = json.load(open(os.path.join(ROOT, "data", "oncall_v21_replica.json"), encoding="utf-8"))
cases = snap["cases"]
n = 3

print(snap["source"], "\n")
for k in range(n):
    acc = sum(c["runs"][k]["top1"] for c in cases) / len(cases)
    print(f"第 {k + 1} 遍：Top1 {acc:.1%}")

always = [c for c in cases if all(r["top1"] == 1 for r in c["runs"])]
never = [c for c in cases if all(r["top1"] == 0 for r in c["runs"])]
flaky = [c for c in cases if c not in always and c not in never]
print(f"\n30 条用例：3 遍都对 {len(always)} 条，3 遍都错 {len(never)} 条，时对时错 {len(flaky)} 条")
for c in flaky:
    marks = "".join("✓" if r["top1"] else "✗" for r in c["runs"])
    wrong = [r["pred"] for r in c["runs"] if not r["top1"]]
    print(f"  {c['case']} {marks}  真实根因 {c['gold']:<26} 答错时选了 {', '.join(wrong)}")


def pass_at_k(c, k):      # 跑 k 次至少对一次的概率（无偏估计：n 次里对了 c 次）
    return 1 - comb(n - c, k) / comb(n, k)


def pass_hat_k(c, k):     # 跑 k 次每次都对的概率
    return comb(c, k) / comb(n, k)


print("\n        pass@k（k 次里至少对一次）   pass^k（k 次全对）")
for k in range(1, n + 1):
    pa = sum(pass_at_k(int(sum(r["top1"] for r in c["runs"])), k) for c in cases) / len(cases)
    ph = sum(pass_hat_k(int(sum(r["top1"] for r in c["runs"])), k) for c in cases) / len(cases)
    print(f"k = {k}      {pa:>6.1%}                     {ph:>6.1%}")

runs = [r for c in cases for r in c["runs"]]
right = [r for r in runs if r["top1"] == 1]
lucky = [r for r in right if r["grounded"] == 0]
wrong = [r for r in runs if r["top1"] == 0]
print(f"\n90 次运行里答对 {len(right)} 次；其中 {len(lucky)} 次没有引用能证明这个根因的证据（结论对，过程不对）")
print(f"答错的 {len(wrong)} 次，平均把握度 {sum(r['confidence'] for r in wrong) / len(wrong):.2f}")
