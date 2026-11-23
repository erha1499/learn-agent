"""单元一 · temperature=0 就完全确定了吗？同一个问题、temperature=0、不传 seed，调 30 次，数一数有几种不同的输出。

    python examples/u01_determinism.py            # 真调模型（30 次）
    python examples/u01_determinism.py --replay
"""
from collections import Counter

from _llm import chat, replay_or_run

PROMPT = "用两句话解释 Redis 为什么会偶尔超时，并给出第一步该查什么。"


def run():
    return {"prompt": PROMPT, "answers": [chat([{"role": "user", "content": PROMPT}], temperature=0, max_tokens=120)["text"].strip()
                                          for _ in range(30)]}


r = replay_or_run("u01_determinism", run)
c = Counter(r["answers"])
print(f"问题：{r['prompt']}\ntemperature=0，30 次里有 {len(c)} 种不同的输出")
for k, (a, n) in enumerate(c.most_common(3), 1):
    print(f"  第 {k} 种 ×{n}：{a.replace(chr(10), ' ')[:90]}…")
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
