"""单元四：挂在最小循环上的三个 harness 机制。循环（mini_agent.run_agent）一行不改，只是传进不同的钩子。

  guard     执行前：工具参数里的实例名，必须是用户自己说过的；不是就拦下，让模型去问
  compress  执行后：日志类结果按“去掉数字后相同”合并成一行加计数，再限制长度
  gate      证据账本 + 提交门：成功的查询结果由程序编上证据号；结论必须通过 submit_conclusion 提交，
            引用的证据号必须真的存在，否则退回；模型不提交就想结束，提醒它提交（最多两次）

    h = Harness(guard=True, compress=True, gate=True)
    a = run_agent(question, SYSTEM_GATE, h.tools(TOOLS), h.execute(execute), **h.hooks())
"""
import json
import re

from mini_world import ROOT_CAUSES

SYSTEM_GATE = ("你是数据库值班助手。先用工具查清楚，再下结论，不要猜。根因只能从下面选一个："
               + "、".join(f"{k}（{v}）" for k, v in ROOT_CAUSES.items())
               + "。查完后调用 submit_conclusion 提交结论，evidence 填支撑结论的证据编号（工具结果开头 [证据 E1] 这样的标记）。")

SUBMIT = {"type": "function", "function": {
    "name": "submit_conclusion",
    "description": "提交排查结论。提交成功后排查结束",
    "parameters": {"type": "object", "properties": {
        "root_cause": {"type": "string", "description": "根因编号"},
        "evidence": {"type": "array", "items": {"type": "string"}, "description": "支撑结论的证据编号，例如 [\"E1\", \"E3\"]"},
        "missing": {"type": "string", "description": "还缺什么信息（查不到证据时填）"}},
        "required": ["root_cause", "evidence"]}}}

MAX_CHARS = 1500


def compress(text):
    """日志去重：把数字换成 #，相同的行合并成“×次数 + 第一次出现的原文”，再截到 MAX_CHARS。"""
    lines = text.split("\n")
    if len(lines) < 30:
        return text
    groups = {}
    for line in lines:
        key = re.sub(r"\d+", "#", line)
        g = groups.setdefault(key, [0, line])
        g[0] += 1
    body = "\n".join(f"×{n} {first}" for n, first in sorted(groups.values(), key=lambda g: g[0]))
    out = f"共 {len(lines)} 行，按内容合并成 {len(groups)} 类（次数少的在前）：\n{body}"
    return out if len(out) <= MAX_CHARS else out[:MAX_CHARS] + f"\n……（已截断，原文 {len(text)} 字符）"


class Harness:
    def __init__(self, guard=False, compress=False, gate=False):
        self.guard, self.compress, self.gate = guard, compress, gate
        self.ledger, self.accepted, self.rejections, self.nudges = {}, None, [], 0

    def tools(self, base):
        return base + [SUBMIT] if self.gate else base

    def execute(self, world_execute):
        def run(name, args):
            if name == "submit_conclusion":
                return self._submit(args)
            return world_execute(name, args)
        return run

    def hooks(self):
        return {"before_tool": self._before, "after_tool": self._after,
                "stop_after_tool": lambda: self.accepted is not None,
                "on_finish": self._on_finish if self.gate else None}

    # ---- 执行前：参数守卫
    def _before(self, name, args, messages):
        if not self.guard or "instance" not in args:
            return None
        said = " ".join(m["content"] for m in messages if m["role"] == "user")
        if args["instance"] not in said:
            return json.dumps({"error": f"用户没有提到实例 {args['instance']}。不要猜实例名，先问用户要查哪台实例。"},
                              ensure_ascii=False)
        return None

    # ---- 执行后：结果压缩 + 证据编号
    def _after(self, name, args, result):
        if name == "submit_conclusion":
            return result
        if self.compress:
            result = compress(result)
        if self.gate and not result.startswith('{"error"'):
            eid = f"E{len(self.ledger) + 1}"
            self.ledger[eid] = name
            result = f"[证据 {eid}] {result}"
        return result

    # ---- 提交门
    def _submit(self, args):
        rc, ev = args.get("root_cause"), args.get("evidence") or []
        if rc == "UNKNOWN":
            self.accepted = {"root_cause": rc, "missing": args.get("missing", "")}
            return "已提交：UNKNOWN"
        reason = None
        if rc not in ROOT_CAUSES:
            reason = f"root_cause 必须是 {', '.join(ROOT_CAUSES)} 之一"
        elif not ev:
            reason = ("没有引用任何证据。结论必须引用查到的证据编号。"
                      "如果确实查不到证据，root_cause 填 UNKNOWN，并在 missing 里写还缺什么")
        elif any(e not in self.ledger for e in ev):
            bad = [e for e in ev if e not in self.ledger]
            reason = (f"证据 {', '.join(bad)} 不存在（已有证据：{', '.join(self.ledger) or '无'}）。"
                      "如果确实查不到证据，root_cause 填 UNKNOWN，并在 missing 里写还缺什么")
        if reason:
            self.rejections.append({"root_cause": rc, "evidence": ev, "reason": reason})
            return json.dumps({"error": "提交被退回：" + reason}, ensure_ascii=False)
        self.accepted = {"root_cause": rc, "evidence": ev}
        return f"已提交：{rc}，证据 {', '.join(ev)}"

    # ---- 想结束时：还没提交就提醒
    def _on_finish(self, text):
        if self.accepted is None and self.nudges < 2:
            self.nudges += 1
            return "你还没有用 submit_conclusion 提交结论。请提交；查不到证据就提交 UNKNOWN。"
        return None
