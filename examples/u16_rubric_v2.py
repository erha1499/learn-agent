"""单元十六 · 把评分细则写清楚以后，两个评委还吵不吵。

u16_judge.py 里，“有依据”这一项 qwen-plus 和 qwen-max 只有一半判得一样。读它们的理由发现，分歧主要来自细则没写清：
  - 推断算不算陈述？（“慢 SQL 导致连接堆积”，可连接数只有 320/1000）
  - 没提到证据里的某些内容，算不算问题？
  - 建议、客套话那几段要不要判？
这里换一份写清了这三点、并附两个别的领域的小例子的细则，在同样 80 份通报上再判一遍，和人工核对过的标签比。

    python examples/u16_rubric_v2.py            # 真调模型（160 次调用）
    python examples/u16_rubric_v2.py --replay
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor

from _llm import replay_or_run
from u16_judge import ask, evidence, human_label, kappa, verdict, CASES

GROUNDED_V2 = """下面是一次数据库故障的排查证据，以及据此写的故障通报。只判断一件事：通报的“结论”和“依据”两段，有没有说证据支持不了的话。

规则：
1. 只看“结论”和“依据”两段，建议和其他段落不在判断范围内。
2. 逐条找出这两段里关于这次故障的陈述：数字、日志内容、系统状态（比如“连接数打满”“连接堆积”“事务长时间持有行锁”）。
3. 一条陈述，证据里能直接看到、或者能从证据直接推出来的，算有依据；证据里看不到、或者和证据矛盾的，算没有依据。
4. 通报没有提到证据里的某些内容，不算问题。

两个别的故障的小例子：
- 证据：CPU 30%，磁盘 IOPS 打满。通报写“CPU 打满导致超时” → 没有依据（证据里 CPU 只有 30%）。
- 证据：磁盘 IOPS 打满，慢查询每分钟 80 条。通报只写了“磁盘 IOPS 打满”，没提慢查询 → 不算问题。

先逐条列出陈述，每条标注有没有依据，最后一行只写：判定: 是（全部有依据） / 否（至少一条没有依据） / 无法判断

【证据】
{ev}

【通报】
{r}"""
JUDGES = [("qwen-plus", 0), ("qwen-max", 0)]


def load_v1():
    with open(os.path.join(os.path.dirname(__file__), "output", "u16_judge.json"), encoding="utf-8") as f:
        return json.load(f)


def run():
    items = load_v1()["items"]
    ev = {c["id"]: evidence(c) for c in CASES}
    jobs = [(i, m, s) for i, it in enumerate(items) for m, s in JUDGES]
    with ThreadPoolExecutor(max_workers=8) as pool:
        outs = list(pool.map(lambda j: ask(GROUNDED_V2.format(ev=ev[items[j[0]]["case"]], r=items[j[0]]["text"]), j[1], j[2]), jobs))
    return {"judgments": [{"idx": i, "model": m, "seed": s, **o} for (i, m, s), o in zip(jobs, outs)]}


def main():
    v1 = load_v1()
    items = v1["items"]
    v2 = replay_or_run("u16_rubric_v2", run)
    truth = [human_label(it, 0) for it in items]
    print("“有依据”一项，和人工核对过的标签比（80 份通报，其中 32 份应判“否”）：")
    preds = {}
    for name, js in (("第一版细则", [j for j in v1["judgments"] if j["kind"] == "grounded"]), ("写清楚的细则", v2["judgments"])):
        for model, seed in JUDGES:
            d = {j["idx"]: j for j in js if j["model"] == model and j["seed"] == seed}
            pred = [verdict(d[i]["text"]) == "是" for i in range(len(items))]
            preds[(name, model)] = pred
            unparsed = sum(verdict(d[i]["text"]) is None for i in range(len(items)))
            fp = sum(p and not y for p, y in zip(pred, truth))
            fn = sum(y and not p for p, y in zip(pred, truth))
            acc = sum(p == y for p, y in zip(pred, truth)) / len(items)
            print(f"  {name}  {model:<9}  准确率 {acc:.0%}  kappa {kappa(pred, truth):.2f}  把没依据的判成有 {fp}  把有依据的判成没有 {fn}  解析不出判定 {unparsed}")
        a, b = preds[(name, "qwen-plus")], preds[(name, "qwen-max")]
        print(f"    两个评委判得一样的：{sum(x == y for x, y in zip(a, b))}/{len(a)}")
    tok = [j["prompt_tokens"] for j in v2["judgments"]]
    print(f"\n写清楚的细则每次判定平均输入 {sum(tok) / len(tok):,.0f} token；{v2['_meta']['date']} 实测")


if __name__ == "__main__":
    main()
