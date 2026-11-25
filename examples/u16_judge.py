"""单元十六 · 让大模型当评委：评委判得准不准，拿标好答案的样本来测。

1. 造样本。迷你评测集的 20 条用例，每条先让模型按证据写一份故障通报（V0，程序核对过里面的数字都在证据里），
   再由程序改出三个变体，所以每份通报的“标准答案”是构造出来的：
     V0 原样                              有依据 ✓  建议对准根因 ✓
     V1 依据里插一句和证据矛盾的数字      有依据 ✗  建议对准根因 ✓
     V2 建议换成另一种根因的处置办法      有依据 ✓  建议对准根因 ✗
     V3 末尾加一段客套话，没有新事实      有依据 ✓  建议对准根因 ✓
2. 几种评委：
     打总分     给证据和通报，“从 1 到 10 打分”
     拆开判     每个问题单独问一次，只答 是 / 否 / 无法判断，先写理由：
                  有依据（给证据）、有依据（不给证据）、建议对准根因
     两两比较   给两份通报，“哪份更好，只答 A 或 B”，两种顺序各问一次
   评委用 qwen-plus（两个种子）和 qwen-max。
3. 打印时从录下的原文重新解析判定，不调模型。

    python examples/u16_judge.py            # 真调模型（约 850 次调用）
    python examples/u16_judge.py --replay   # 只看结果
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor

from _llm import chat, replay_or_run
from mini_eval import CASES
from mini_world import ROOT_CAUSES

ADVICE = {
    "MAX_CONNECTIONS": "1. 临时调大最大连接数，并排查应用有没有连接泄漏；2. 检查连接池配置，限制单个应用能占用的连接数。",
    "SLOW_SQL": "1. 给慢查询涉及的表补上合适的索引；2. 优化扫描行数最多的那条 SQL，必要时先对报表查询限流。",
    "LOCK_WAIT": "1. 找出长时间持有行锁的事务并终止；2. 缩短热点行上的事务，避免在事务里做远程调用。",
    "DISK_FULL": "1. 清理过期的 binlog 和日志文件，先释放磁盘空间；2. 扩容数据盘，并加上磁盘使用率告警。",
    "NETWORK": "1. 联系网络组排查应用到数据库之间的链路丢包；2. 必要时把流量切到备用链路。",
}
CONFUSE = {"MAX_CONNECTIONS": "SLOW_SQL", "SLOW_SQL": "MAX_CONNECTIONS", "LOCK_WAIT": "SLOW_SQL",
           "DISK_FULL": "LOCK_WAIT", "NETWORK": "MAX_CONNECTIONS"}
FLUFF = ("补充说明：本次故障影响了部分业务，值班团队高度重视，第一时间响应并组织排查。我们会持续关注该实例的运行状态，"
         "后续将结合本次经验进一步完善监控告警和应急预案，不断提升系统的稳定性。如有任何疑问，请随时联系值班同学，感谢大家的理解与配合。")
LABELS = {"V0": (True, True), "V1": (False, True), "V2": (True, False), "V3": (True, True)}   # (有依据, 建议对准根因)
# 人工核对：作者逐条读了 20 份 V0，程序的数字核对只查了数字，漏掉了站不住的状态描述：
#   C05、C07、C08 写“慢 SQL 导致连接堆积”，可连接数只有 320/1000；C19 写“连接数达到上限”，实际 880/1000，
#   而且把根因写成了连接数打满（证据给的是网络问题）。这 4 份的 V0、V2、V3 “有依据”应为否。
#   C19 的结论本来就是连接数打满，V2 换上的正好是连接数的处置办法，所以它的 V2 “建议对准根因”应为是。
#   “有依据”只看结论和依据两段；V3 末尾那段客套话里“影响了部分业务”也找不到依据，按这个口径不在判断范围内。
UNSUPPORTED_V0 = {"C05", "C07", "C08", "C19"}


def human_label(item, k):
    grounded, targeted = LABELS[item["variant"]]
    if k == 0:
        return grounded and item["case"] not in UNSUPPORTED_V0
    return True if (item["case"], item["variant"]) == ("C19", "V2") else targeted
JUDGES = [("qwen-plus", 0), ("qwen-plus", 1), ("qwen-max", 0)]


def evidence(c):
    return (f"实例：{c['instance']}\n监控指标：{json.dumps(c['metrics'], ensure_ascii=False)}\n"
            f"慢查询日志：\n" + "\n".join(c["slow_log"]) + "\n错误日志：\n" + "\n".join(c["error_log"]) +
            f"\n网络检查：{json.dumps(c['network'], ensure_ascii=False)}\n排查结论：根因 {c['cause']}（{ROOT_CAUSES[c['cause']]}）")


WRITE = ("下面是一次数据库故障的排查证据和结论。给业务方写一段故障通报，严格按这个格式写三段：\n"
         "结论：一句话说清根因\n依据：两三句，只原样引用证据里出现过的数字和日志，不要自己统计次数\n"
         "建议：1. …… 2. ……（两条处置建议，针对这个根因，不写具体数值）\n纯文本，不要用 Markdown 符号。\n\n{ev}")


def numbers(t):
    return re.findall(r"\d+(?:\.\d+)?", t)


def write_v0(c):
    ev = evidence(c)
    for attempt in range(4):
        text = chat([{"role": "user", "content": WRITE.format(ev=ev)}], seed=100 * attempt + int(c["id"][1:]))["text"]
        m = re.search(r"结论\**\s*[:：](.*?)依据\**\s*[:：](.*?)建议\**\s*[:：](.*)", text, re.S)
        if m and set(numbers(m.group(1) + m.group(2))) <= set(numbers(ev)):
            return {"text": text.strip(), "attempts": attempt + 1}
    return {"text": text.strip(), "attempts": 4, "unchecked": True}


def variants(c, v0):
    m = re.search(r"建议\**\s*[:：]", v0)
    head = v0[:m.end()]
    if c["cause"] == "NETWORK":
        assert c["metrics"]["cpu_pct"] < 90
        fake = "监控还显示 CPU 使用率达到 97%。"
    else:
        assert c["network"]["loss_pct"] < 1
        fake = "网络检查还显示丢包率达到 18%。"
    pre = v0[:m.start()].rstrip()
    v1 = pre + ("" if pre[-1] in "。；;" else "。") + fake + "\n" + v0[m.start():]
    v2 = head + ADVICE[CONFUSE[c["cause"]]]
    v3 = v0 + "\n\n" + FLUFF
    return {"V0": v0, "V1": v1, "V2": v2, "V3": v3}


HOLISTIC = ("下面是一次数据库故障的排查证据，以及值班工程师据此写给业务方的故障通报。"
            "请从 1 到 10 给这份通报打分，10 分最好。只输出一个数字。\n\n【证据】\n{ev}\n\n【通报】\n{r}")
GROUNDED = ("下面是一次数据库故障的排查证据，以及据此写的故障通报。只判断一件事：通报里的每一条事实陈述（尤其是数字），"
            "是否都能在证据里找到依据？证据里没有的、和证据矛盾的，都算没有依据。处置建议不在判断范围内。\n"
            "先用一两句话说明理由，最后一行只写：判定: 是 / 否 / 无法判断\n\n【证据】\n{ev}\n\n【通报】\n{r}")
GROUNDED_NOEV = ("下面是一份数据库故障通报。只判断一件事：通报里的每一条事实陈述（尤其是数字），是否都有依据、没有编造？"
                 "处置建议不在判断范围内。\n先用一两句话说明理由，最后一行只写：判定: 是 / 否 / 无法判断\n\n【通报】\n{r}")
TARGETED = ("下面是一份数据库故障通报。只判断一件事：“建议”里的两条处置建议，是否都针对“结论”里写的那个根因？\n"
            "先用一两句话说明理由，最后一行只写：判定: 是 / 否 / 无法判断\n\n【通报】\n{r}")
PAIR = ("下面是一次数据库故障的排查证据，以及两份据此写给业务方的故障通报 A 和 B。哪一份更好？只回答 A 或 B。\n\n"
        "【证据】\n{ev}\n\n【通报 A】\n{a}\n\n【通报 B】\n{b}")


def ask(prompt, model, seed):
    r = chat([{"role": "user", "content": prompt}], model=model, seed=seed)
    return {"text": r["text"], "prompt_tokens": r["usage"].get("prompt_tokens", 0),
            "completion_tokens": r["usage"].get("completion_tokens", 0)}


def run():
    with ThreadPoolExecutor(max_workers=8) as pool:
        v0s = list(pool.map(write_v0, CASES))
        items = []
        for c, v0 in zip(CASES, v0s):
            for v, text in variants(c, v0["text"]).items():
                items.append({"case": c["id"], "variant": v, "text": text, "v0_attempts": v0["attempts"],
                              "v0_unchecked": v0.get("unchecked", False)})
        ev = {c["id"]: evidence(c) for c in CASES}
        jobs = []
        for i, it in enumerate(items):
            for model, seed in JUDGES:
                jobs.append(("grounded", i, model, seed, GROUNDED.format(ev=ev[it["case"]], r=it["text"])))
                jobs.append(("targeted", i, model, seed, TARGETED.format(r=it["text"])))
            for seed in (0, 1):
                jobs.append(("holistic", i, "qwen-plus", seed, HOLISTIC.format(ev=ev[it["case"]], r=it["text"])))
            jobs.append(("grounded_noev", i, "qwen-plus", 0, GROUNDED_NOEV.format(r=it["text"])))
        by = {(it["case"], it["variant"]): it["text"] for it in items}
        pairs = []
        for c in CASES:
            for other in ("V3", "V1"):
                for first in ("V0", other):
                    second = other if first == "V0" else "V0"
                    pairs.append({"case": c["id"], "pair": f"V0-{other}", "A": first, "B": second})
                    jobs.append(("pair", len(pairs) - 1, "qwen-plus", 0,
                                 PAIR.format(ev=ev[c["id"]], a=by[(c["id"], first)], b=by[(c["id"], second)])))
        outs = list(pool.map(lambda j: ask(j[4], j[2], j[3]), jobs))
    judgments = [{"kind": j[0], "idx": j[1], "model": j[2], "seed": j[3], **o} for j, o in zip(jobs, outs)]
    return {"items": items, "pairs": pairs, "judgments": judgments}


def verdict(text):
    """取最后一个“判定”后面的 是 / 否 / 无法判断；也认“### 判定”换行再写的格式。取不到返回 None，单独统计。"""
    m = re.findall(r"判定[\s:：#*\-]*(是|否|无法判断)", text or "")
    return m[-1] if m else None


def score(text):
    m = re.search(r"\b(10|[1-9])\b", text or "")
    return int(m.group(1)) if m else None


def kappa(a, b):
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def main():
    r = replay_or_run("u16_judge", run)
    items, J = r["items"], r["judgments"]
    print(f"样本：{len(items)} 份通报（20 条用例 × 4 个版本）；V0 重写次数分布 "
          f"{sorted({it['v0_attempts'] for it in items})}，没通过数字核对的 {sum(it['v0_unchecked'] for it in items) // 4} 份")

    def get(kind, model="qwen-plus", seed=0):
        return {j["idx"]: j for j in J if j["kind"] == kind and j["model"] == model and j["seed"] == seed}

    print("\n=== 一、打总分（qwen-plus，种子 0）：各版本的平均分，和 ≥8 分的比例")
    h = get("holistic")
    for v in LABELS:
        s = [score(h[i]["text"]) for i, it in enumerate(items) if it["variant"] == v]
        ok = [x for x in s if x is not None]
        print(f"  {v}  平均 {sum(ok) / len(ok):.1f} 分  分数 {sorted(ok)}  ≥8 分 {sum(x >= 8 for x in ok)}/{len(s)}")
    h1 = get("holistic", seed=1)
    same = sum(score(h[i]["text"]) == score(h1[i]["text"]) for i in range(len(items)))
    print(f"  两个种子给出同一个分数：{same}/{len(items)}")

    print("\n=== 二、拆开判：各版本被判“是”的比例（qwen-plus，种子 0）")
    g, t, gn = get("grounded"), get("targeted"), get("grounded_noev")
    for v in LABELS:
        idx = [i for i, it in enumerate(items) if it["variant"] == v]
        cnt = lambda d, val: sum(verdict(d[i]["text"]) == val for i in idx)
        print(f"  {v}  有依据（给证据）{cnt(g, '是')}/{len(idx)}  有依据（不给证据）{cnt(gn, '是')}/{len(idx)}"
              f"  建议对准根因 {cnt(t, '是')}/{len(idx)}")
    unk = sum(verdict(j["text"]) == "无法判断" for j in J if j["kind"] in ("grounded", "targeted", "grounded_noev"))
    bad = sum(verdict(j["text"]) is None for j in J if j["kind"] in ("grounded", "targeted", "grounded_noev"))
    print(f"  所有拆开判的调用里：答“无法判断” {unk} 次，没按格式写判定 {bad} 次")

    print("\n=== 三、和人工核对过的标准答案比：准确率和 Cohen's kappa（“无法判断”算判错）")
    for kind, k in (("grounded", 0), ("targeted", 1)):
        construct = [LABELS[it["variant"]][k] for it in items]
        truth = [human_label(it, k) for it in items]
        print(f"  {'有依据' if k == 0 else '对准根因'}：人工核对改了 {sum(x != y for x, y in zip(construct, truth))} 个标签")
        for model, seed in JUDGES:
            d = get(kind, model, seed)
            pred = [verdict(d[i]["text"]) == "是" for i in range(len(items))]
            acc = sum(p == y for p, y in zip(pred, truth)) / len(items)
            print(f"  {'有依据' if k == 0 else '对准根因'}  {model} 种子{seed}  准确率 {acc:.0%}  kappa {kappa(pred, truth):.2f}")
        a = [verdict(get(kind)[i]["text"]) == "是" for i in range(len(items))]
        b = [verdict(get(kind, seed=1)[i]["text"]) == "是" for i in range(len(items))]
        c = [verdict(get(kind, "qwen-max")[i]["text"]) == "是" for i in range(len(items))]
        print(f"    同一模型两个种子的一致率 {sum(x == y for x, y in zip(a, b)) / len(a):.0%}；qwen-plus 和 qwen-max 的一致率 "
              f"{sum(x == y for x, y in zip(a, c)) / len(a):.0%}")
    truth = [human_label(it, 0) and human_label(it, 1) for it in items]
    for model, seed in JUDGES:
        gg, tt = get("grounded", model, seed), get("targeted", model, seed)
        pred = [verdict(gg[i]["text"]) == "是" and verdict(tt[i]["text"]) == "是" for i in range(len(items))]
        print(f"  两项都过  {model} 种子{seed}  准确率 {sum(p == y for p, y in zip(pred, truth)) / len(items):.0%}")
    hp = [score(h[i]["text"]) is not None and score(h[i]["text"]) >= 8 for i in range(len(items))]
    print(f"  打总分 ≥8 当作通过  准确率 {sum(p == y for p, y in zip(hp, truth)) / len(items):.0%}  kappa {kappa(hp, truth):.2f}")

    print("\n=== 四、两两比较（qwen-plus）")
    pj = {j["idx"]: j for j in J if j["kind"] == "pair"}
    for pair in ("V0-V3", "V0-V1"):
        rows = [(i, p) for i, p in enumerate(r["pairs"]) if p["pair"] == pair]
        letter = lambda i: (re.search(r"(?<![A-Za-z])([AB])(?![A-Za-z])", pj[i]["text"] or "") or [None, None])[1]
        pick = lambda i, p: p["A"] if letter(i) == "A" else p["B"]
        first = sum(letter(i) == "A" for i, _ in rows)
        v0 = sum(pick(i, p) == "V0" for i, p in rows)
        by_case = {}
        for i, p in rows:
            by_case.setdefault(p["case"], []).append(pick(i, p))
        flips = sum(len(set(v)) > 1 for v in by_case.values())
        print(f"  {pair}：{len(rows)} 次比较，选了排在前面的 {first} 次，选了 V0 {v0} 次；"
              f"同一对换个顺序就改判的 {flips}/{len(by_case)} 对")

    print("\n=== 五、每次判定的输入 token（平均）")
    for kind in ("holistic", "grounded", "grounded_noev", "targeted", "pair"):
        xs = [j["prompt_tokens"] for j in J if j["kind"] == kind]
        print(f"  {kind:<14} {sum(xs) / len(xs):,.0f}")
    print(f"\n模型 {r['_meta']['model']} 写通报，评委 qwen-plus / qwen-max，{r['_meta']['date']} 实测")


if __name__ == "__main__":
    main()
