"""单元八 · 上下文不共享：两个 Agent 各写一半故障通报，会不会对不上？

S4（user-mysql-04 写入全部失败）的故障通报分两部分：“根因分析”由一个带工具的排查 Agent 写，“处置建议”由另一个 Agent 写。
三种分工，每种 5 遍（每遍的排查结果相同，只换写建议的方式）：
  A. 并行、不共享：写建议的 Agent 只看到用户的原话，和排查同时进行
  B. 顺序、共享：写建议的 Agent 拿到排查 Agent 的完整分析再写
  C. 并行 + 评审：先按 A 写，再让一个评审检查“建议是否针对分析出的根因”，不一致就把分析交给写建议的 Agent 重写
程序检查建议是否“对准根因”：提到磁盘相关的处置（清理、扩容、空间……），并且没有把条目花在其他根因上（连接数、锁、慢 SQL、网络、只读）。
判定在打印时按录下的原文重新计算，改了规则直接 --replay 就能看到新结果。

    python examples/u08_shared_context.py            # 真调模型（约 50 次）
    python examples/u08_shared_context.py --replay
"""
import json
import re

from _llm import chat, replay_or_run
from mini_agent import run_agent
from mini_world import SCENARIOS, SYSTEM, TOOLS, execute, verdict

S = SCENARIOS["S4"]
WRITER = "你是值班助手，负责写故障通报里的“处置建议”部分：最多 3 条，每条一句话，具体可执行。只输出建议。"
REVIEWER = ("你是故障通报的评审。检查“处置建议”是否针对“根因分析”里得出的根因。"
            '只输出 JSON：{"consistent": true 或 false, "reason": "一句话"}')
DISK = re.compile(r"磁盘|空间|清理|扩容|binlog|日志文件|No space|errno 28", re.I)
OTHER = re.compile(r"连接数|max_connections|连接池|锁等待|死锁|长事务|慢 ?SQL|慢查询(?!日志)|索引|网络|丢包|只读|read_only")  # 清理“慢查询日志”文件是在腾磁盘，不算


def targeted(text):
    return bool(DISK.search(text)) and not OTHER.search(text)


def write(content, seed):
    return chat([{"role": "system", "content": WRITER}, {"role": "user", "content": content}], seed=seed)["text"].strip()


def run():
    out = {"A": [], "B": [], "C": []}
    for seed in range(5):
        a = run_agent(S["question"], SYSTEM, TOOLS, execute, seed=seed)
        analysis = a["answer"]
        diag = {"pred": verdict(analysis), "tokens": sum(t["prompt_tokens"] + t["completion_tokens"] for t in a["trace"])}
        alone = write(f"用户报告：{S['question']}", seed)
        shared = write(f"用户报告：{S['question']}\n\n排查 Agent 的根因分析：\n{analysis}", seed)
        out["A"].append({**diag, "suggestions": alone, "targeted": targeted(alone)})
        out["B"].append({**diag, "suggestions": shared, "targeted": targeted(shared)})
        rv = chat([{"role": "system", "content": REVIEWER},
                   {"role": "user", "content": f"根因分析：\n{analysis}\n\n处置建议：\n{alone}"}],
                  response_format={"type": "json_object"}, seed=seed)["text"]
        try:
            verdict_rv = json.loads(rv)
        except json.JSONDecodeError:
            verdict_rv = {"consistent": True, "reason": "评审输出无法解析"}
        final = alone
        if not verdict_rv.get("consistent", True):
            final = write(f"用户报告：{S['question']}\n\n排查 Agent 的根因分析：\n{analysis}\n\n"
                          f"你之前写的建议被评审退回：{verdict_rv.get('reason')}。请重写。", seed)
        out["C"].append({**diag, "review": verdict_rv, "suggestions": final, "targeted": targeted(final),
                         "first_targeted": targeted(alone)})
    return out


r = replay_or_run("u08_shared_context", run)
print("排查 Agent 的结论：", [x["pred"] for x in r["A"]], "\n")
labels = {"A": "A. 并行、不共享", "B": "B. 顺序、共享", "C": "C. 并行 + 评审"}
for k in "ABC":
    runs = r[k]
    print(f"{labels[k]}：建议对准根因 {sum(targeted(x['suggestions']) for x in runs)}/5")
    for x in runs:
        if not targeted(x["suggestions"]):
            print(f"    没对准：还在查 {sorted(set(m.group(0) for m in OTHER.finditer(x['suggestions'])))}")
c = r["C"]
first = [targeted(x["suggestions"]) for x in r["A"]]          # C 组评审前的建议，就是同一遍 A 组的建议
rejected = [not x["review"].get("consistent", True) for x in c]
print(f"\nC 组：评审退回 {sum(rejected)}/5 次；评审前没对准的 {first.count(False)} 次全被退回："
      f"{all(rej for rej, ok in zip(rejected, first) if not ok)}；退回理由（第 1 遍）：{c[0]['review'].get('reason')}")
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
