"""单元一 · 采样：同一个问题问 10 遍，答案有多少种？temperature 和 seed 各起什么作用？

    python examples/u01_sampling.py            # 真调模型（约 70 次很短的调用）
    python examples/u01_sampling.py --replay
"""
from collections import Counter

from _llm import chat, replay_or_run

ONE = "Redis 偶尔超时，最可能的原因是什么？只回答一个词，不要解释。"
TITLE = "用户反馈“Redis 偶尔超时”。给这个问题写一个排查工单的标题，20 个字以内，只输出标题。"


def ask(prompt, t, seed=None):
    params = {"temperature": t, "max_tokens": 40}
    if seed is not None:
        params["seed"] = seed
    return chat([{"role": "user", "content": prompt}], **params)["text"].strip()


def run():
    out = {}
    for t in (0.0, 0.7, 1.5):
        out[f"一个词 · temperature={t} · 不传 seed"] = [ask(ONE, t) for _ in range(10)]
    for t in (0.7, 1.5):
        out[f"一个词 · temperature={t} · 每次换 seed"] = [ask(ONE, t, 1000 + i) for i in range(10)]
    out["工单标题 · temperature=1.5 · 不传 seed"] = [ask(TITLE, 1.5) for _ in range(10)]
    out["工单标题 · temperature=1.5 · 每次换 seed"] = [ask(TITLE, 1.5, 3000 + i) for i in range(10)]
    return {"prompts": {"一个词": ONE, "工单标题": TITLE}, "answers": out}


r = replay_or_run("u01_sampling", run)
for k, v in r["prompts"].items():
    print(f"{k}：{v}")
print()
for name, ans in r["answers"].items():
    c = Counter(ans)
    top = "  ".join(f"{k}×{n}" for k, n in c.most_common(3))
    print(f"{name}：{len(c)} 种   {top}{'  …' if len(c) > 3 else ''}")
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
