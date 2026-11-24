"""把 content/ 生成一个单页网站 docs/index.html。只用标准库，正文以 content/ 为准，网页是生成的副本。

    python scripts/build.py

支持正文用到的 Markdown 子集：标题、段落、粗体、行内代码、链接、无序 / 有序列表、表格、代码块、引用。
- 「深入一层（可跳过）：标题」渲染成默认收起的折叠块，范围到下一个同级或更高级的标题为止；
- 「自测」里的每道题配上 answers.json 里的答案（键是题目原文），缺答案时一次列出所有缺的题再报错；
- 指向 NN-*.md 的链接变成页内跳转；
- 导航按导读里的「### 第X部分」分组：每个部分下面表格里链到的单元归这个部分；
  部分标题和表格之间的说明（写给谁、先要会什么），在网页里挪到这个部分第一个单元的前面，导读里不再重复。
"""
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT, OUT = ROOT / "content", ROOT / "docs" / "index.html"
INLINE = [(re.compile(r"`([^`]+)`"), lambda m: f"<code>{m.group(1)}</code>"),
          (re.compile(r"\*\*(.+?)\*\*"), lambda m: f"<b>{m.group(1)}</b>")]
LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def slug(text):
    return re.sub(r"[^\w一-鿿]+", "-", text).strip("-").lower()


def inline(text, units):
    out, last = [], 0
    for m in LINK.finditer(text):   # 链接先拆出来，文字部分再做转义和行内格式
        out.append(_fmt(text[last:m.start()]))
        label, href = m.group(1), m.group(2)
        if re.match(r"\d\d-[\w-]+\.md$", href) and href in units:
            href = "#" + units[href]
        out.append(f'<a href="{html.escape(href)}">{_fmt(label)}</a>')
        last = m.end()
    out.append(_fmt(text[last:]))
    return "".join(out)


def _fmt(s):
    s = html.escape(s, quote=False)
    for pat, fn in INLINE:
        s = pat.sub(fn, s)
    return s


def render(md, units, answers, missing, unit_id):
    lines, out, i = md.split("\n"), [], 0
    open_details = None          # 当前折叠块所在的标题级别
    in_quiz = False
    while i < len(lines):
        line = lines[i]
        h = re.match(r"^(#{1,4}) (.+)$", line)
        if h:
            level, title = len(h.group(1)), h.group(2).strip()
            if open_details is not None and level <= open_details:
                out.append("</div></details>")
                open_details = None
            in_quiz = title == "自测"
            deep = re.match(r"深入一层（可跳过）[:：]\s*(.+)", title)
            if deep:
                out.append(f'<details class="deep"><summary><span class="tag">深入一层</span>{inline(deep.group(1), units)}</summary><div>')
                open_details = level
            else:
                hid = unit_id if level == 1 else f"{unit_id}-{slug(title)}"
                out.append(f'<h{level} id="{hid}">{inline(title, units)}</h{level}>')
            i += 1
            continue
        if line.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            code = html.escape("\n".join(lines[i + 1:j]))
            out.append(f"<pre><code>{code}</code></pre>")
            i = j + 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            head, body = rows[0], rows[1:]
            t = "<thead><tr>" + "".join(f"<th>{inline(c, units)}</th>" for c in head) + "</tr></thead><tbody>"
            t += "".join("<tr>" + "".join(f"<td>{inline(c, units)}</td>" for c in r) + "</tr>" for r in body)
            out.append(f'<div class="tbl"><table>{t}</tbody></table></div>')
            continue
        if line.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i][1:].strip())
                i += 1
            out.append(f"<blockquote>{inline(' '.join(buf), units)}</blockquote>")
            continue
        m = re.match(r"^(\s*)(-|\d+\.) (.+)$", line)
        if m:
            ordered = m.group(2) != "-"
            items = []
            while i < len(lines):
                mm = re.match(r"^(\s*)(-|\d+\.) (.+)$", lines[i])
                if not mm or (mm.group(2) != "-") != ordered:
                    break
                text = mm.group(3)
                i += 1
                while i < len(lines) and lines[i].startswith("  ") and not re.match(r"^\s*(-|\d+\.) ", lines[i]):
                    text += " " + lines[i].strip()
                    i += 1
                items.append(text)
            if in_quiz and ordered:
                qs = []
                for q in items:
                    a = answers.get(q)
                    if a is None:
                        missing.append(q)
                    qs.append(f'<li><details class="qz"><summary>{inline(q, units)}</summary><div class="ans">{a or ""}</div></details></li>')
                out.append('<ol class="quiz">' + "".join(qs) + "</ol>")
            else:
                tag = "ol" if ordered else "ul"
                out.append(f"<{tag}>" + "".join(f"<li>{inline(x, units)}</li>" for x in items) + f"</{tag}>")
            continue
        if not line.strip():
            i += 1
            continue
        buf = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#|```|\||>|\s*(-|\d+\.) )", lines[i]):
            buf.append(lines[i])
            i += 1
        out.append(f"<p>{inline(' '.join(buf), units)}</p>")
    if open_details is not None:
        out.append("</div></details>")
    return "\n".join(out)


CSS = """
:root{--bg:#fff;--fg:#1d2129;--mut:#6b7280;--line:#e5e8ef;--soft:#f5f7fa;--acc:#2f6bff;--code:#f2f4f7;--deep:#f7f8fb}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0f1115;--fg:#e6e8eb;--mut:#9aa1ad;--line:#2a2f37;--soft:#161920;--acc:#5b8cff;--code:#1a1d23;--deep:#13161b}}
:root[data-theme=dark]{--bg:#0f1115;--fg:#e6e8eb;--mut:#9aa1ad;--line:#2a2f37;--soft:#161920;--acc:#5b8cff;--code:#1a1d23;--deep:#13161b}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.75 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
.wrap{display:flex;max-width:1240px;margin:0 auto}
nav{position:sticky;top:0;height:100vh;overflow:auto;width:260px;flex:none;padding:28px 18px;border-right:1px solid var(--line);font-size:14px}
nav .brand{font-weight:700;font-size:16px;margin-bottom:18px}
nav a{display:block;color:var(--fg);text-decoration:none;padding:5px 8px;border-radius:6px;opacity:.85}
nav a:hover{background:var(--soft);opacity:1}nav .sub{padding-left:20px;font-size:13px;opacity:.7}
nav a.part{margin:18px 0 4px;font-size:12px;font-weight:600;color:var(--mut)}
.part-intro{margin:3.2em 0 0;padding:16px 20px;background:var(--soft);border-radius:10px}
.part-intro .part-name{font-weight:700;font-size:1.2rem;margin-bottom:.3em}.part-intro p{margin:.4em 0}
.part-intro+section h1{border-top:none;margin-top:1.4em}
main{min-width:0;flex:1;padding:36px 56px 120px}
h1{font-size:1.75rem;line-height:1.35;margin:2.4em 0 .8em;padding-top:.4em;border-top:1px solid var(--line)}
section:first-of-type h1{border-top:none;margin-top:0}
h2{font-size:1.3rem;margin:2em 0 .6em}h3{font-size:1.08rem;margin:1.6em 0 .5em}
p,li{max-width:46em}a{color:var(--acc)}
code{font:.88em "SF Mono",Menlo,monospace;background:var(--code);padding:.1em .35em;border-radius:4px}
pre{background:var(--code);padding:14px 16px;border-radius:8px;overflow:auto;font-size:13.5px;line-height:1.6}pre code{background:none;padding:0}
.tbl{overflow-x:auto;margin:1em 0}table{border-collapse:collapse;font-size:14.5px;min-width:60%}
th,td{border:1px solid var(--line);padding:7px 11px;text-align:left;vertical-align:top}th{background:var(--soft);font-weight:600}
blockquote{margin:1em 0;padding:10px 16px;border-left:3px solid var(--acc);background:var(--soft);border-radius:0 8px 8px 0}
details.deep{border:1px solid var(--line);background:var(--deep);border-radius:10px;padding:2px 16px;margin:1.2em 0}
details.deep summary{cursor:pointer;padding:10px 0;font-weight:600}
.tag{font-size:12px;font-weight:600;color:var(--acc);border:1px solid var(--acc);border-radius:999px;padding:1px 8px;margin-right:8px}
ol.quiz{padding-left:1.4em}ol.quiz li{margin:.5em 0}
details.qz summary{cursor:pointer}details.qz .ans{margin:.6em 0 1em;padding:10px 14px;background:var(--soft);border-radius:8px}
.toggle{position:fixed;right:18px;top:14px;border:1px solid var(--line);background:var(--bg);color:var(--fg);border-radius:8px;padding:4px 10px;cursor:pointer;font-size:13px}
@media (max-width:860px){nav{display:none}main{padding:24px 16px 80px}.toggle{top:10px;right:10px}}
"""


def parts(guide):
    """导读里「### 第X部分 名字」下面的表格链到哪些单元，就归哪个部分。
    返回 ({文件名: 部分名}, {部分名: 标题和表格之间的说明})。"""
    of, intro, cur, in_table = {}, {}, None, False
    for line in guide.split("\n"):
        h = re.match(r"^### (第.+?部分.*)$", line)
        if h:
            cur, in_table = h.group(1).strip(), False
            intro[cur] = []
        elif line.startswith("#"):
            cur = None
        elif cur:
            for href in re.findall(r"\]\((\d\d-[\w-]+\.md)\)", line):
                of[href] = cur
            in_table = in_table or line.startswith("|")
            if line.strip() and not in_table:          # 只收标题和表格之间的说明
                intro[cur].append(line)
    return of, {k: "\n".join(v) for k, v in intro.items()}


def main():
    answers = json.loads((CONTENT / "answers.json").read_text(encoding="utf-8"))
    files = sorted(CONTENT.glob("[0-9][0-9]-*.md"))
    units = {f.name: f"u{f.name[:2]}" for f in files}
    guide = (CONTENT / "README.md").read_text(encoding="utf-8")
    part_of, intro = parts(guide)
    page_guide = guide
    for part in set(part_of.values()):         # 有单元的部分：说明挪到部分开头，导读里删掉
        if intro[part]:
            assert page_guide.count(intro[part]) == 1, part
            page_guide = page_guide.replace(intro[part] + "\n", "", 1)
    missing, sections, nav, last_part = [], [], [], None
    for name, md in [("README.md", page_guide)] + [(f.name, f.read_text(encoding="utf-8")) for f in files]:
        uid = units.get(name, "guide")
        part = part_of.get(name)
        if name in units and part != last_part:
            last_part, pid = part, f"part-{uid}"
            sections.append(f'<section class="part-intro" id="{pid}"><div class="part-name">{html.escape(part or "")}</div>'
                            f'{render(intro.get(part, ""), units, answers, missing, pid)}</section>')
            nav.append(f'<a class="part" href="#{pid}">{html.escape(part or "")}</a>')
        sections.append(f'<section>{render(md, units, answers, missing, uid)}</section>')
        title = re.search(r"^# (.+)$", md, re.M).group(1)
        nav.append(f'<a href="#{uid}">{html.escape(title)}</a>')
        for sub in re.findall(r"^## (.+)$", md, re.M):
            if not sub.startswith(("做项目时", "面试常问", "自测", "延伸阅读", "导读")):
                nav.append(f'<a class="sub" href="#{uid}-{slug(sub)}">{html.escape(sub)}</a>')
    if missing:
        sys.exit("这些自测题没有答案（answers.json 的键要和题目原文一样）：\n- " + "\n- ".join(missing))
    page = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>learn-agent</title><style>{CSS}</style></head>
<body><button class="toggle" onclick="var r=document.documentElement;r.dataset.theme=(r.dataset.theme||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'))==='dark'?'light':'dark'" aria-label="切换深浅色">◐</button>
<div class="wrap"><nav><div class="brand">learn-agent</div>{''.join(nav)}</nav><main>{''.join(sections)}</main></div></body></html>"""
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}：{len(files)} 个单元，{len(answers)} 道自测题，{len(page) // 1024} KB")


if __name__ == "__main__":
    main()
