"""单元五 · 改一个文件里的几行：让模型重写整个文件，还是只给“把这段换成那段”？

被改的文件是 examples/mini_repo/inventory.py（约 170 行）。任务：把 reserve_stock 的预占超时从 3 秒改成 5 秒，
并在超时抛异常之前打一条 warning 日志。两种工具各跑 3 遍（每次换 seed），文件放在临时目录里改，不动仓库里的原件：
  A. read_file + write_file：改文件 = 把整个新文件写出来
  B. read_file + edit_file：改文件 = 给出一段原文和替换后的文字，原文必须在文件里恰好出现一次（Claude Code、pi 的做法）
检查：改完的文件能不能解析、要求的两处改了没有、reserve_stock 之外有没有被顺手改动。

    python examples/u05_edit.py            # 真调模型（约 20 次，A 组每次要写出整个文件）
    python examples/u05_edit.py --replay
"""
import ast
import difflib
import json
import os
import shutil
import tempfile

from _llm import replay_or_run
from mini_agent import run_agent

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mini_repo", "inventory.py")
TASK = ("把 inventory.py 里 reserve_stock 的预占超时从 3 秒改成 5 秒，并且在超时抛异常之前打一条 warning 日志，"
        "带上 sku_id 和 order_id。其他代码不要动。改完回复一句话说明改了什么。")
SYSTEM = "你是一个编程助手，工作目录里有一个 Python 项目。用工具读文件、改文件，不要只在回复里贴代码。"

READ = {"type": "function", "function": {"name": "read_file", "description": "读取一个文件的全部内容",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}}
WRITE = {"type": "function", "function": {"name": "write_file", "description": "用 content 覆盖整个文件",
         "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                        "required": ["path", "content"]}}}
EDIT = {"type": "function", "function": {
    "name": "edit_file",
    "description": "把文件里的一段原文替换成新文字。old_text 必须和文件内容逐字相同，并且在文件里只出现一次",
    "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"},
                                                    "new_text": {"type": "string"}},
                   "required": ["path", "old_text", "new_text"]}}}


def make_execute(root):
    def safe(path):
        full = os.path.realpath(os.path.join(root, path))
        if not full.startswith(os.path.realpath(root) + os.sep):
            raise ValueError("只能访问工作目录里的文件")
        return full

    def execute(name, args):
        try:
            path = safe(args.get("path", ""))
            if name == "read_file":
                return open(path, encoding="utf-8").read()
            if name == "write_file":
                open(path, "w", encoding="utf-8").write(args["content"])
                return f"已写入 {len(args['content'])} 个字符"
            if name == "edit_file":
                text = open(path, encoding="utf-8").read()
                n = text.count(args["old_text"])
                if n != 1:
                    return json.dumps({"error": f"old_text 在文件里出现了 {n} 次，必须恰好 1 次"}, ensure_ascii=False)
                open(path, "w", encoding="utf-8").write(text.replace(args["old_text"], args["new_text"]))
                return "已修改"
        except (OSError, ValueError, KeyError) as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        return json.dumps({"error": f"没有叫 {name} 的工具"}, ensure_ascii=False)
    return execute


def check(original, new):
    """能否解析、两处要求、reserve_stock 之外改了几行。"""
    out = {"parses": True, "timeout_5": False, "warning": False, "outside_changed": 0, "lines": len(new.splitlines())}
    try:
        tree = ast.parse(new)
    except SyntaxError:
        out["parses"] = False
        return out
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "reserve_stock")
    body = ast.get_source_segment(new, fn)
    out["timeout_5"] = "time.time() + 5" in body and "time.time() + 3" not in body
    out["warning"] = "log.warning" in body or "log.warn(" in body
    ofn = next(n for n in ast.walk(ast.parse(original)) if isinstance(n, ast.FunctionDef) and n.name == "reserve_stock")
    lo, hi = ofn.lineno, ofn.end_lineno
    sm = difflib.SequenceMatcher(None, original.splitlines(), new.splitlines())
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal" and not (i1 >= lo - 1 and i2 <= hi):
            out["outside_changed"] += max(i2 - i1, j2 - j1)
    return out


def run():
    original = open(SRC, encoding="utf-8").read()
    res = {}
    for mode, tools in (("write", [READ, WRITE]), ("edit", [READ, EDIT])):
        res[mode] = []
        for seed in range(3):
            root = tempfile.mkdtemp()
            shutil.copy(SRC, root)
            a = run_agent(TASK, SYSTEM, tools, make_execute(root), seed=seed)
            new = open(os.path.join(root, "inventory.py"), encoding="utf-8").read()
            shutil.rmtree(root)
            res[mode].append({**check(original, new), "turns": len(a["trace"]), "seconds": a["seconds"],
                              "prompt_tokens": sum(t["prompt_tokens"] for t in a["trace"]),
                              "completion_tokens": sum(t["completion_tokens"] for t in a["trace"]),
                              "calls": [c["name"] for t in a["trace"] for c in t["calls"]], "answer": a["answer"]})
    return {"original_lines": len(original.splitlines()), **res}


r = replay_or_run("u05_edit", run)
avg = lambda xs: sum(xs) / len(xs)  # noqa: E731
print(f"被改的文件 {r['original_lines']} 行\n")
for mode, label in (("write", "A. 重写整个文件"), ("edit", "B. 字符串替换")):
    runs = r[mode]
    ok = sum(x["parses"] and x["timeout_5"] and x["warning"] and x["outside_changed"] == 0 for x in runs)
    print(f"{label}：完全做对 {ok}/3，每遍输出 {avg([x['completion_tokens'] for x in runs]):,.0f} token，"
          f"输入 {avg([x['prompt_tokens'] for x in runs]):,.0f} token，耗时 {avg([x['seconds'] for x in runs]):.0f} 秒")
    for i, x in enumerate(runs, 1):
        print(f"    第 {i} 遍：能解析 {x['parses']}，超时改成 5 {x['timeout_5']}，加了 warning {x['warning']}，"
              f"reserve_stock 之外改动 {x['outside_changed']} 行，改完 {x['lines']} 行，工具 {x['calls']}")
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
