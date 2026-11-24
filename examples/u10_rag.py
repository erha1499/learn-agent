"""单元十 · RAG：不检索、检索一次、让 Agent 自己检索，答对多少？

知识库是 examples/mini_kb/ 下 18 篇虚构公司的内部文档（CMDB、值班群、规定、复盘、手册）。9 道题：
  单跳（负责人、DDL 规定、备份时间、从库名）、多跳（要连读两篇）、换了说法（“写不进去”对“磁盘写满”）、
  桥接多跳（先查到负责人是谁，再拿这个人名去找第二篇）、知识库里没有答案（应该说没有）。
  检索器：BM25（按两字片段切词）、向量（百炼 text-embedding-v4）、两者用 RRF 融合。先比三种检索器的召回。
  三种回答方式，每题各 2 遍（每次换 seed）：
    A. 不检索：只靠模型自己
    B. 经典 RAG：按问题检索一次，取前 3 篇全文放进提示词
    C. Agentic RAG：检索做成工具 search_kb / read_doc，模型自己决定搜什么、搜几次、读哪篇
  检查：答案里有没有关键事实（没答案的题要明确说没有）；B、C 有没有看到该看的文档；token 和调用次数。

    python examples/u10_rag.py            # 真调模型（约 90 次对话 + 几十次向量化）
    python examples/u10_rag.py --replay
"""
import json
import math
import os
import re
import urllib.request

from _llm import BASE, _ctx, chat, replay_or_run
from mini_agent import run_agent

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mini_kb")
DOCS = {f[:-3]: open(os.path.join(DIR, f), encoding="utf-8").read().strip() for f in sorted(os.listdir(DIR))}

QUESTIONS = [  # (问题, 判对的正则, 该看的文档, 类型)
    ("order-mysql-01 的负责人是谁？", r"周岚", ["cmdb-order"], "单跳"),
    ("线上大表做 DDL 有什么规定？什么时间能做？", r"02[:：]00", ["policy-ddl"], "单跳"),
    ("报表库每天几点做全量备份？", r"03[:：]30", ["cmdb-report"], "单跳，有冲突"),
    ("库存那台库的从库叫什么？", r"inventory-mysql-06", ["cmdb-inventory"], "单跳，别名"),
    ("pay-mysql-03 的负责人所在的团队，值班群是哪个？", r"pay-oncall", ["cmdb-pay", "team-oncall"], "多跳"),
    ("之前那次连接数打满的事故，后来定了什么规范？现在每个应用实例的连接池上限是多少？", r"25", ["postmortem-2025-11-conn", "policy-pool"], "多跳，有更新"),
    ("数据库写不进去但读没问题，以前遇到过吗？当时怎么处理的？", r"PURGE|2 ?TB", ["postmortem-2026-03-disk"], "换了说法"),
    ("order-mysql-01 的负责人还负责哪台数据库？", r"user-mysql-04", ["cmdb-order", "cmdb-user"], "桥接多跳"),
    ("cache-redis-02 的最大内存（maxmemory）配置是多少？", None, [], "没有答案"),
]
REFUSE = re.compile(r"没有|未找到|找不到|无法确定|未提及|不包含|未记录|没提到|无相关|不知道")


def correct(q, answer):
    pattern = QUESTIONS[q][1]
    if pattern is None:                                  # 没有答案的题：要说没有，且不能给出一个具体数值
        return bool(REFUSE.search(answer)) and not re.search(r"\d+\s*(GB|G|MB|gb|mb)", answer)
    return bool(re.search(pattern, answer))


# ---------- 检索器 ----------
def grams(s):
    s = re.sub(r"\s+", "", s.lower())
    return [s[i:i + 2] for i in range(len(s) - 1)]


DOC_GRAMS = {k: grams(v) for k, v in DOCS.items()}
AVGDL = sum(len(g) for g in DOC_GRAMS.values()) / len(DOC_GRAMS)


def bm25(query, k1=1.5, b=0.75):
    q = set(grams(query))
    n = len(DOC_GRAMS)
    scores = {}
    for d, g in DOC_GRAMS.items():
        s = 0.0
        for t in q:
            tf = g.count(t)
            if tf:
                df = sum(1 for gg in DOC_GRAMS.values() if t in gg)
                s += math.log(1 + (n - df + 0.5) / (df + 0.5)) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(g) / AVGDL))
        scores[d] = s
    return sorted(scores, key=lambda d: -scores[d])


def embed(texts):
    body = {"model": "text-embedding-v4", "input": texts, "dimensions": 512}
    req = urllib.request.Request(BASE + "/embeddings", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"})
    with urllib.request.urlopen(req, timeout=60, context=_ctx()) as r:
        return [x["embedding"] for x in json.loads(r.read())["data"]]


DOC_VECS = None


def vector(query):
    global DOC_VECS
    if DOC_VECS is None:
        names = list(DOCS)
        vecs = embed([DOCS[n] for n in names[:10]]) + embed([DOCS[n] for n in names[10:]])   # 每批最多 10 条
        DOC_VECS = dict(zip(names, vecs))
    qv = embed([query])[0]
    cos = {d: sum(a * b for a, b in zip(qv, v)) / (math.hypot(*qv) * math.hypot(*v)) for d, v in DOC_VECS.items()}
    return sorted(cos, key=lambda d: -cos[d])


def hybrid(query, k=60):
    ranks = {}
    for ranking in (bm25(query), vector(query)):
        for i, d in enumerate(ranking):
            ranks[d] = ranks.get(d, 0) + 1 / (k + i + 1)     # RRF：两种排名的倒数相加
    return sorted(ranks, key=lambda d: -ranks[d])


# ---------- 三种回答方式 ----------
SYS_A = "你是值班助手，回答公司内部数据库相关的问题。不知道就说不知道，不要猜。"
SYS_B = "你是值班助手。只根据给出的资料回答公司内部数据库相关的问题；资料里没有就明确说没有，不要猜。"
SYS_C = ("你是值班助手，回答公司内部数据库相关的问题。必须先用 search_kb 搜索知识库，需要时用 read_doc 读全文；"
         "可以多次搜索、换关键词。知识库里没有就明确说没有，不要猜。回答时注明依据的文档编号。")
SEARCH = {"type": "function", "function": {"name": "search_kb", "description": "在公司内部知识库里搜索，返回最相关的 3 篇文档的编号、标题和开头",
                                           "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}
READ = {"type": "function", "function": {"name": "read_doc", "description": "读取一篇文档的全文",
                                         "parameters": {"type": "object", "properties": {"doc_id": {"type": "string"}}, "required": ["doc_id"]}}}


def closed_book(q, seed):
    r = chat([{"role": "system", "content": SYS_A}, {"role": "user", "content": QUESTIONS[q][0]}], seed=seed)
    return {"answer": r["text"], "calls": 1, "tokens": r["usage"]["prompt_tokens"] + r["usage"]["completion_tokens"], "seen": []}


def classic(q, seed, retriever):
    top = retriever(QUESTIONS[q][0])[:3]
    ctx = "\n\n".join(f"[{d}]\n{DOCS[d]}" for d in top)
    r = chat([{"role": "system", "content": SYS_B}, {"role": "user", "content": f"资料：\n{ctx}\n\n问题：{QUESTIONS[q][0]}"}], seed=seed)
    return {"answer": r["text"], "calls": 1, "tokens": r["usage"]["prompt_tokens"] + r["usage"]["completion_tokens"], "seen": top}


def agentic(q, seed, retriever):
    seen, queries = [], []

    def ex(name, args):
        if name == "search_kb":
            queries.append(args.get("query", ""))
            top = retriever(args.get("query", ""))[:3]
            seen.extend(d for d in top if d not in seen)
            return json.dumps([{"doc_id": d, "title": DOCS[d].splitlines()[0].lstrip("# "), "head": DOCS[d].splitlines()[1][:60]}
                               for d in top], ensure_ascii=False)
        if name == "read_doc":
            d = args.get("doc_id", "")
            return DOCS.get(d, json.dumps({"error": f"没有文档 {d}"}, ensure_ascii=False))
        return '{"error": "没有这个工具"}'

    a = run_agent(QUESTIONS[q][0], SYS_C, [SEARCH, READ], ex, max_turns=8, seed=seed)
    return {"answer": a["answer"] or "", "calls": len(a["trace"]), "queries": queries, "seen": seen,
            "tokens": sum(t["prompt_tokens"] + t["completion_tokens"] for t in a["trace"])}


def run():
    recall = {}
    for name, fn in (("bm25", bm25), ("vector", vector), ("hybrid", hybrid)):
        recall[name] = [[d for d in fn(q)[:3]] for q, _, _, _ in QUESTIONS]
    out = {"recall": recall, "A": [], "B": [], "C": []}
    for q in range(len(QUESTIONS)):
        for seed in range(2):
            out["A"].append({"q": q, **closed_book(q, seed)})
            out["B"].append({"q": q, **classic(q, seed, vector)})
            out["C"].append({"q": q, **agentic(q, seed, vector)})
    return out


r = replay_or_run("u10_rag", run)
n_ans = sum(1 for q in QUESTIONS if q[2])
print(f"=== 检索召回（共 {n_ans} 道有答案的题）：第 1 篇就是该看的文档 / 前 3 篇包含全部该看的文档")
for name, label in (("bm25", "BM25"), ("vector", "向量"), ("hybrid", "融合")):
    top1 = sum(r["recall"][name][i][0] in QUESTIONS[i][2] for i in range(len(QUESTIONS)) if QUESTIONS[i][2])
    hit = [all(d in r["recall"][name][i] for d in QUESTIONS[i][2]) for i in range(len(QUESTIONS)) if QUESTIONS[i][2]]
    miss = [QUESTIONS[i][3] for i in range(len(QUESTIONS)) if QUESTIONS[i][2] and not all(d in r["recall"][name][i] for d in QUESTIONS[i][2])]
    print(f"  {label:<6}第 1 篇对 {top1}/{n_ans}，前 3 篇全 {sum(hit)}/{n_ans}  没召回全的：{miss}")
print(f"\n=== 回答（{len(QUESTIONS)} 题 × 2 遍）")
avg = lambda xs: sum(xs) / len(xs)  # noqa: E731
labels = {"A": "A. 不检索", "B": "B. 经典 RAG（检索一次，前 3 篇）", "C": "C. Agentic RAG"}
for k in "ABC":
    runs = r[k]
    right = sum(correct(x["q"], x["answer"]) for x in runs)
    by_type = {}
    for x in runs:
        by_type.setdefault(QUESTIONS[x["q"]][3], []).append(correct(x["q"], x["answer"]))
    print(f"{labels[k]}：答对 {right}/{len(runs)}，每题调模型 {avg([x['calls'] for x in runs]):.1f} 次，每题 {avg([x['tokens'] for x in runs]):,.0f} token")
    print("    " + "；".join(f"{t} {sum(v)}/{len(v)}" for t, v in by_type.items()))
c_multi = [x for x in r["C"] if len(QUESTIONS[x["q"]][2]) == 2]
print("\nC 组多跳题的搜索词：", [x["queries"] for x in c_multi])
bridge = [i for i, q in enumerate(QUESTIONS) if q[3] == "桥接多跳"][0]
print("B 组桥接题检索到的文档：", [x["seen"] for x in r["B"] if x["q"] == bridge])
print("B 组桥接题的回答：", [x["answer"][-90:] for x in r["B"] if x["q"] == bridge])
wrong_a = [x["answer"][:80] for x in r["A"] if QUESTIONS[x["q"]][1] and correct(x["q"], x["answer"]) is False][:2]
print("A 组答错的样子：", wrong_a)
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测；向量模型 text-embedding-v4（512 维）")
