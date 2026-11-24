"""单元六 · 让模型输出程序能用的 JSON：四种做法，哪种靠得住？

任务：把值班群里的一条消息整理成工单 JSON（实例名、严重程度、现象、开始时间）。4 条消息，其中一条没提实例名，一条没提时间。
四种做法，每条消息各跑 5 遍（每次换 seed），共 20 次：
  A. 只靠提示词：“只输出 JSON，字段如下……”；A+ 是在 A 的基础上，校验失败就把错误发回去让它改一次
  B. JSON 模式：response_format={"type": "json_object"}，保证是合法 JSON，不管字段
  C. JSON Schema 严格模式：response_format 里给出 schema，strict=true
  D. 强制工具调用：把 schema 写成一个工具的参数，tool_choice 指定必须调它
程序校验：能不能直接 json.loads、字段和类型对不对、严重程度是不是三选一、时间是不是 HH:MM；再对标准答案看值对不对。

    python examples/u06_structured.py            # 真调模型（约 110 次，每次很短）
    python examples/u06_structured.py --replay
"""
import json
import re
import urllib.error

from _llm import chat, replay_or_run

SCHEMA = {"type": "object", "properties": {
    "instance": {"type": ["string", "null"], "description": "实例名，消息里没提就填 null"},
    "severity": {"type": "string", "enum": ["P0", "P1", "P2"]},
    "symptoms": {"type": "array", "items": {"type": "string"}},
    "started_at": {"type": ["string", "null"], "description": "开始时间，格式 HH:MM，没提就填 null"}},
    "required": ["instance", "severity", "symptoms", "started_at"], "additionalProperties": False}

RULES = ("严重程度：P0 = 核心业务不可用；P1 = 部分功能受损或明显变慢；P2 = 偶发、影响小。"
         "消息里没提到的字段填 null，不要猜。")
SYSTEM = "你是值班助手，把用户的消息整理成工单。" + RULES
PROMPT_ONLY = (SYSTEM + "只输出 JSON，不要输出其他内容。字段：instance（字符串或 null）、severity（P0/P1/P2）、"
               "symptoms（字符串数组）、started_at（HH:MM 或 null）。")

MESSAGES = {
    "M1": ("@值班 order-mysql-01 从 14:05 开始下单全挂，报 Too many connections，用户已经在投诉了！！",
           {"instance": "order-mysql-01", "severity": "P0", "started_at": "14:05"}),
    "M2": ("report-mysql-02 报表这两天偶尔慢一下，不急，有空帮看看",
           {"instance": "report-mysql-02", "severity": "P2", "started_at": None}),
    "M3": ("pay-mysql-03 支付回调从 10:12 起大概三成超时，重试能过",
           {"instance": "pay-mysql-03", "severity": "P1", "started_at": "10:12"}),
    "M4": ("数据库好像有点问题，好几个接口变慢了，大概 9 点半开始的",
           {"instance": None, "severity": "P1", "started_at": "09:30"}),
}
TOOL = {"type": "function", "function": {"name": "create_ticket", "description": "创建一张值班工单", "parameters": SCHEMA}}


def validate(text):
    """返回 (对象或 None, 问题列表)。"""
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None, ["不是合法 JSON"]
    problems = []
    if not isinstance(obj, dict):
        return None, ["顶层不是对象"]
    for k in SCHEMA["required"]:
        if k not in obj:
            problems.append(f"缺字段 {k}")
    for k in obj:
        if k not in SCHEMA["properties"]:
            problems.append(f"多了字段 {k}")
    if "severity" in obj and obj["severity"] not in ("P0", "P1", "P2"):
        problems.append(f"severity={obj['severity']!r} 不在 P0/P1/P2 里")
    if "instance" in obj and not (obj["instance"] is None or isinstance(obj["instance"], str)):
        problems.append("instance 类型不对")
    if "symptoms" in obj and not (isinstance(obj["symptoms"], list) and all(isinstance(x, str) for x in obj["symptoms"])):
        problems.append("symptoms 不是字符串数组")
    t = obj.get("started_at")
    if t is not None and not (isinstance(t, str) and re.fullmatch(r"\d{2}:\d{2}", t)):
        problems.append(f"started_at={t!r} 不是 HH:MM")
    return obj, problems


def call(mode, msg, seed):
    if mode in ("A", "A+"):
        msgs = [{"role": "system", "content": PROMPT_ONLY}, {"role": "user", "content": msg}]
        r = chat(msgs, seed=seed)
        text, retried = r["text"], False
        obj, problems = validate(text)
        if mode == "A+" and problems:                      # 校验失败：把问题发回去，让它改一次
            retried = True
            msgs += [{"role": "assistant", "content": text},
                     {"role": "user", "content": "你的输出有问题：" + "；".join(problems) + "。请只输出修正后的 JSON。"}]
            text = chat(msgs, seed=seed)["text"]
        return text, retried
    if mode == "B":
        return chat([{"role": "system", "content": PROMPT_ONLY}, {"role": "user", "content": msg}],
                    response_format={"type": "json_object"}, seed=seed)["text"], False
    if mode == "C":
        return chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": msg}],
                    response_format={"type": "json_schema", "json_schema": {"name": "ticket", "schema": SCHEMA, "strict": True}},
                    seed=seed)["text"], False
    r = chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": msg}], tools=[TOOL],
             tool_choice={"type": "function", "function": {"name": "create_ticket"}}, seed=seed)
    return (r["tool_calls"][0]["function"]["arguments"] if r["tool_calls"] else r["text"]), False


def run():
    out = {}
    for mode in ("A", "A+", "B", "C", "D"):
        out[mode] = []
        for mid, (msg, gold) in MESSAGES.items():
            for seed in range(5):
                try:
                    text, retried = call(mode, msg, seed)
                except urllib.error.HTTPError as e:
                    text, retried = f"HTTP {e.code}: {e.read().decode()[:200]}", False
                obj, problems = validate(text)
                out[mode].append({"msg": mid, "text": text[:300], "retried": retried, "problems": problems,
                                  "correct": {k: (obj or {}).get(k, "缺") == v for k, v in gold.items()} if obj else None})
    return out


r = replay_or_run("u06_structured", run)
labels = {"A": "A  只靠提示词", "A+": "A+ 提示词 + 校验失败重试一次", "B": "B  JSON 模式", "C": "C  JSON Schema 严格模式",
          "D": "D  强制工具调用"}
print(f"{'做法':<26}{'合法 JSON':>10}{'符合 schema':>12}{'严重程度对':>10}{'实例名对':>9}{'时间对':>8}")
for mode, runs in r.items():
    if mode == "_meta":
        continue
    parsed = [x for x in runs if x["correct"] is not None]
    ok = [x for x in parsed if not x["problems"]]
    def right(k):
        return sum(1 for x in parsed if x["correct"][k])
    print(f"{labels[mode]:<26}{len(parsed):>7}/20{len(ok):>9}/20{right('severity'):>9}/20{right('instance'):>7}/20{right('started_at'):>6}/20")
for mode in ("A", "B", "C", "D"):
    probs = [p for x in r[mode] for p in x["problems"]]
    if probs:
        print(f"\n{labels[mode]} 的问题（取前 4 条）：{probs[:4]}")
        bad = next(x["text"] for x in r[mode] if x["problems"])
        print(f"    原样输出：{bad[:160]!r}")
wrong_m4 = [x["text"][:120] for m in ("C", "D") for x in r[m] if x["msg"] == "M4" and x["correct"] and not x["correct"]["instance"]]
if wrong_m4:
    print("\nM4（消息里没有实例名）在 C、D 里实例名填错的样子：", wrong_m4[:2])
retried = [x for x in r["A+"] if x["retried"]]
print(f"\nA+ 里触发重试 {len(retried)} 次，重试后符合 schema {sum(not x['problems'] for x in retried)} 次")
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
