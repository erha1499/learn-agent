"""单元十三 · 同一个 Agent 跑 3 遍：结果稳不稳？pass@k 和 pass^k 是什么？结论对的，过程靠得住吗？

读 u13_run.py 录下的结果（迷你评测集 20 条用例 × 3 遍），不调模型：
    python examples/u13_repeats.py
"""
import json
import os
from math import comb

ROOT = os.path.dirname(os.path.abspath(__file__))
r = json.load(open(os.path.join(ROOT, "output", "u13_run.json"), encoding="utf-8"))
cases = r["cases"]
n = len(cases[0]["runs"])

for k in range(n):
    print(f"第 {k + 1} 遍：答对 {sum(c['runs'][k]['correct'] for c in cases)}/{len(cases)}")

always = [c for c in cases if all(x["correct"] for x in c["runs"])]
never = [c for c in cases if not any(x["correct"] for x in c["runs"])]
flaky = [c for c in cases if c not in always and c not in never]
print(f"\n{len(cases)} 条用例：{n} 遍都对 {len(always)} 条，{n} 遍都错 {len(never)} 条，时对时错 {len(flaky)} 条")
for c in flaky + never:
    marks = "".join("✓" if x["correct"] else "✗" for x in c["runs"])
    wrong = [x["pred"] for x in c["runs"] if not x["correct"]]
    print(f"  {c['id']} {c['level']:<9}{marks}  真实根因 {c['cause']:<16} 答错时选了 {wrong}")

print("\n按难度：")
for level in ("plain", "distract", "mislead", "flaky"):
    runs = [x for c in cases if c["level"] == level for x in c["runs"]]
    print(f"  {level:<9}答对 {sum(x['correct'] for x in runs)}/{len(runs)}")


def pass_at_k(c, k):
    return 1 - comb(n - c, k) / comb(n, k)


def pass_hat_k(c, k):
    return comb(c, k) / comb(n, k)


print("\n        pass@k（k 次里至少对一次）   pass^k（k 次全对）")
for k in range(1, n + 1):
    pa = sum(pass_at_k(sum(x["correct"] for x in c["runs"]), k) for c in cases) / len(cases)
    ph = sum(pass_hat_k(sum(x["correct"] for x in c["runs"]), k) for c in cases) / len(cases)
    print(f"k = {k}      {pa:>6.1%}                     {ph:>6.1%}")

runs = [(c, x) for c in cases for x in c["runs"]]
right = [(c, x) for c, x in runs if x["correct"]]
lucky = [(c, x) for c, x in right if not x["key_evidence"]]
wrong = [(c, x) for c, x in runs if not x["correct"]]
print(f"\n{len(runs)} 次运行答对 {len(right)} 次；其中 {len(lucky)} 次没拿到关键证据（结论对，过程站不住）：",
      [(c["id"], c["level"]) for c, x in lucky])
print(f"答错的 {len(wrong)} 次，平均调了 {sum(len(x['calls']) for _, x in wrong) / max(1, len(wrong)):.1f} 次工具；"
      f"答对的平均调了 {sum(len(x['calls']) for _, x in right) / len(right):.1f} 次")
zero = [(c["id"], x["pred"]) for c, x in runs if not x["calls"]]
print(f"一次工具都没调就下结论的运行：{zero}")
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
