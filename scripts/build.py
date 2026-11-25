"""把 content/ 生成一个单页网站 docs/index.html。只用标准库，正文以 content/ 为准，网页是生成的副本。

    python scripts/build.py

页面骨架、样式、脚本在 scripts/site/（page.html、style.css、app.js），构建时内联进一个文件。

支持正文用到的 Markdown 子集：标题、段落、粗体、行内代码、链接、反斜杠转义、无序 / 有序列表、表格、代码块、引用。
- 「深入一层（可跳过）：标题」渲染成默认收起的折叠块，范围到下一个同级或更高级的标题为止；
- 「自测」里的每道题配上 answers.json 里的答案（键是题目原文），缺答案时一次列出所有缺的题再报错；
- 指向 NN-*.md 的链接变成页内跳转；「见 N.M」「N.M 节」链到那一节，找不到就报错；
- 导航按导读里的「### 第X部分」分组：每个部分下面表格里链到的单元归这个部分；
  部分标题和表格之间的说明（写给谁、先要会什么），在网页里挪到这个部分第一个单元的开头，导读里不再重复。
"""
import html
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT, SITE, OUT = ROOT / "content", ROOT / "scripts" / "site", ROOT / "docs" / "index.html"
NAV_SKIP = ("做项目时", "面试常问", "自测", "延伸阅读", "导读")   # 这些二级标题不进导航

BLOCK_START = re.compile(r"^(#{1,4} |```|\||>|\s*(-|\d+\.) )")
LIST_ITEM = re.compile(r"^\s*(-|\d+\.) (.+)$")
CODE = re.compile(r"`([^`]+)`")
ESCAPE = re.compile(r"\\([\\`*_\[\]()#|>-])")
LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
BOLD = re.compile(r"\*\*(.+?)\*\*")
XREF = re.compile(r"(见 ?)(\d{1,2}\.\d{1,2})(?![\d.])|(?<![\d.])(\d{1,2}\.\d{1,2})( ?节)(?!点)")
SECNUM = re.compile(r"^(\d{1,2}\.\d{1,2}) ")
STASH = re.compile(r"\x00(\d+)\x00")
CJK = re.compile(r"[　-〿一-鿿＀-￯]")

esc = html.escape


def slug(text):
    return re.sub(r"[^\w一-鿿]+", "-", text).strip("-").lower()


def plain(md):
    """标题里的 Markdown 去掉标记，给 title 属性和网页标题用。"""
    return BOLD.sub(r"\1", CODE.sub(r"\1", ESCAPE.sub(r"\1", md)))


def join_lines(lines):
    """段落里的折行：中文和中文之间直接接上，其余补一个空格。"""
    out = lines[0]
    for nxt in lines[1:]:
        out += nxt if CJK.match(out[-1:]) and CJK.match(nxt[:1]) else " " + nxt
    return out


@dataclass
class Unit:
    file: str
    uid: str
    md: str
    num: int = 0
    name: str = ""            # 「单元三」后面的完整标题
    short: str = ""           # 冒号前的部分，用在导航和翻页
    part: str | None = None
    sections: list = field(default_factory=list)   # 导航里的二级标题 [(id, html)]
    body: str = ""


class Book:
    """跨单元共享的东西：单元表、已用的 id、小节编号、答案。"""

    def __init__(self, units, answers):
        self.files = {u.file: u.uid for u in units}
        self.answers = answers
        self.missing = []         # 没有答案的自测题
        self.ids = set()
        self.secnum = {}          # "21.6" -> 那一节的 id
        self.xrefs = set()        # 正文里引用过的小节编号

    def new_id(self, base):
        hid, n = base, 2
        while hid in self.ids:
            hid, n = f"{base}-{n}", n + 1
        self.ids.add(hid)
        return hid

    def inline(self, text):
        """行内格式。代码和转义先存起来，剩下的文字转义后再处理链接、粗体、小节引用。"""
        stash = []

        def keep(s):
            stash.append(s)
            return f"\x00{len(stash) - 1}\x00"

        text = CODE.sub(lambda m: keep(f"<code>{esc(m.group(1))}</code>"), text)
        text = ESCAPE.sub(lambda m: keep(esc(m.group(1))), text)
        text = esc(text, quote=False)
        text = LINK.sub(self._link, text)
        text = BOLD.sub(r"<b>\1</b>", text)
        text = XREF.sub(self._xref, text)
        while STASH.search(text):
            text = STASH.sub(lambda m: stash[int(m.group(1))], text)
        return text

    def _link(self, m):
        label, href = m.group(1), m.group(2)
        if href in self.files:
            return f'<a href="#{self.files[href]}">{label}</a>'
        if href.startswith("http"):
            return f'<a href="{href}" target="_blank" rel="noopener">{label}</a>'
        return f'<a href="{href}">{label}</a>'

    def _xref(self, m):
        num = m.group(2) or m.group(3)
        self.xrefs.add(num)
        link = f'<a href="#\x01{num}\x01">{num}</a>'      # 全书渲染完再换成真实 id
        return f"{m.group(1)}{link}" if m.group(1) else f"{link}{m.group(4)}"

    def resolve_xrefs(self, page):
        lost = sorted(self.xrefs - self.secnum.keys())
        if lost:
            sys.exit("这些小节引用找不到对应的小节：" + "、".join(lost))
        return re.sub(r"\x01([\d.]+)\x01", lambda m: self.secnum[m.group(1)], page)


class Renderer:
    """把一个单元的 Markdown 渲染成 HTML，顺带收集导航用的二级标题。"""

    def __init__(self, book, uid):
        self.book, self.uid = book, uid
        self.sections = []
        self.out = []
        self.deep = None          # 当前折叠块所在的标题级别
        self.quiz = False

    def render(self, md):
        self.lines, self.i = md.split("\n"), 0
        while self.i < len(self.lines):
            line = self.lines[self.i]
            if re.match(r"^#{1,4} ", line):
                self.heading(line)
            elif line.startswith("```"):
                self.code()
            elif line.startswith("|"):
                self.table()
            elif line.startswith(">"):
                self.quote()
            elif LIST_ITEM.match(line):
                self.list()
            elif not line.strip():
                self.i += 1
            else:
                self.para()
        self.close_deep()
        return "\n".join(self.out)

    def take_while(self, cond):
        start = self.i
        while self.i < len(self.lines) and cond(self.lines[self.i]):
            self.i += 1
        return self.lines[start:self.i]

    def close_deep(self, level=0):
        if self.deep is not None and level <= self.deep:
            self.out.append("</div></details>")
            self.deep = None

    def heading(self, line):
        hashes, title = line.split(" ", 1)
        level, title = len(hashes), title.strip()
        self.i += 1
        self.close_deep(level)
        self.quiz = title == "自测"
        deep = re.match(r"深入一层（可跳过）[:：]\s*(.+)", title)
        if deep:
            self.out.append(f'<details class="deep"><summary><span class="tag">深入一层</span>'
                            f'{self.book.inline(deep.group(1))}</summary><div>')
            self.deep = level
            return
        hid = self.book.new_id(self.uid if level == 1 else f"{self.uid}-{slug(title)}")
        body = self.book.inline(title)
        self.out.append(f'<h{level} id="{hid}">{body}</h{level}>')
        if level == 2:
            num = SECNUM.match(title)
            if num:
                self.book.secnum[num.group(1)] = hid
            if not title.startswith(NAV_SKIP):
                self.sections.append((hid, body))

    def code(self):
        self.i += 1
        body = self.take_while(lambda s: not s.startswith("```"))
        self.i += 1
        self.out.append(f'<div class="code"><pre><code>{esc(chr(10).join(body))}</code></pre></div>')

    def table(self):
        rows = [[c.strip() for c in line.strip().strip("|").split("|")]
                for line in self.take_while(lambda s: s.startswith("|"))]
        rows = [r for r in rows if not all(re.fullmatch(r":?-{3,}:?", c) for c in r)]
        cells = lambda r, tag: "".join(f"<{tag}>{self.book.inline(c)}</{tag}>" for c in r)
        body = "".join(f"<tr>{cells(r, 'td')}</tr>" for r in rows[1:])
        self.out.append(f'<div class="tbl"><table><thead><tr>{cells(rows[0], "th")}</tr></thead>'
                        f"<tbody>{body}</tbody></table></div>")

    def quote(self):
        text = " ".join(s[1:].strip() for s in self.take_while(lambda s: s.startswith(">")))
        self.out.append(f"<blockquote>{self.book.inline(text)}</blockquote>")

    def list(self):
        ordered = LIST_ITEM.match(self.lines[self.i]).group(1) != "-"
        items = []
        while self.i < len(self.lines):
            m = LIST_ITEM.match(self.lines[self.i])
            if not m or (m.group(1) != "-") != ordered:
                break
            self.i += 1
            more = self.take_while(lambda s: s.startswith("  ") and not LIST_ITEM.match(s))
            items.append(" ".join([m.group(2)] + [s.strip() for s in more]))
        if self.quiz and ordered:
            self.out.append('<ol class="quiz">' + "".join(map(self.question, items)) + "</ol>")
        else:
            tag = "ol" if ordered else "ul"
            self.out.append(f"<{tag}>" + "".join(f"<li>{self.book.inline(x)}</li>" for x in items) + f"</{tag}>")

    def question(self, q):
        a = self.book.answers.get(q)
        if a is None:
            self.book.missing.append(q)
        return f'<li><details class="qz"><summary>{self.book.inline(q)}</summary><div class="ans">{a or ""}</div></details></li>'

    def para(self):
        buf = [self.lines[self.i]]
        self.i += 1
        buf += self.take_while(lambda s: s.strip() and not BLOCK_START.match(s))
        self.out.append(f"<p>{self.book.inline(join_lines(buf))}</p>")


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


def load():
    guide = (CONTENT / "README.md").read_text(encoding="utf-8")
    part_of, intro = parts(guide)
    for part in set(part_of.values()):         # 有单元的部分：说明挪到部分开头，导读里删掉
        if intro[part]:
            assert guide.count(intro[part]) == 1, part
            guide = guide.replace(intro[part] + "\n", "", 1)
    units = [Unit("README.md", "guide", guide, name="导读", short="导读")]
    for f in sorted(CONTENT.glob("[0-9][0-9]-*.md")):
        md = f.read_text(encoding="utf-8")
        h1 = re.search(r"^# 单元\S+ (.+)$", md, re.M)
        assert h1, f"{f.name} 的一级标题要写成「# 单元X 标题」"
        name = plain(h1.group(1).strip())
        units.append(Unit(f.name, f"u{f.name[:2]}", md, num=int(f.name[:2]), name=name,
                          short=name.split("：")[0], part=part_of.get(f.name)))
    return units, intro


def render_units(units, intro, book):
    articles = []
    for k, u in enumerate(units):
        head = ""
        if u.part and u.part != units[k - 1].part:
            pid = book.new_id(f"part-{u.uid}")
            text = Renderer(book, pid).render(intro.get(u.part, ""))
            head = f'<div class="part-intro" id="{pid}"><div class="part-name">{esc(u.part)}</div>{text}</div>'
        r = Renderer(book, u.uid)
        body = r.render(u.md)
        u.sections = r.sections
        prev, nxt = units[k - 1] if k else None, units[k + 1] if k + 1 < len(units) else None
        pager = "".join([
            f'<a class="prev" href="#{prev.uid}" title="{esc(prev.name)}">← {esc(prev.short)}</a>' if prev else "",
            f'<a class="next" href="#{nxt.uid}" title="{esc(nxt.name)}">{esc(nxt.short)} →</a>' if nxt else "",
        ])
        label = f"{u.num} {u.short}" if u.num else u.short
        articles.append(f'<article class="unit" data-unit="{u.uid}" data-label="{esc(label)}">'
                        f'{head}{body}<div class="pager">{pager}</div></article>')
    return "\n".join(articles)


def render_nav(units):
    out, last = [], None
    for u in units:
        if u.part != last:
            last = u.part
            if u.part:
                out.append(f'<div class="group">{esc(u.part)}</div>')
        num = u.num or ""
        out.append(f'<a class="u" href="#{u.uid}" data-unit="{u.uid}" title="{esc(u.name)}">'
                   f'<span class="n">{num}</span><span>{esc(u.short)}</span></a>')
        if u.sections:
            links = "".join(f'<li><a href="#{hid}">{title}</a></li>' for hid, title in u.sections)
            out.append(f'<ol class="secs" data-unit="{u.uid}">{links}</ol>')
    return "".join(out)


def fill(template, **parts):
    for key, value in parts.items():
        mark = "{{" + key + "}}"
        assert template.count(mark) == 1, f"page.html 里要有且只有一个 {mark}"
        template = template.replace(mark, value)
    return template


def main():
    answers = json.loads((CONTENT / "answers.json").read_text(encoding="utf-8"))
    units, intro = load()
    book = Book(units, answers)
    main_html = render_units(units, intro, book)
    if book.missing:
        sys.exit("这些自测题没有答案（answers.json 的键要和题目原文一样）：\n- " + "\n- ".join(book.missing))
    page = fill((SITE / "page.html").read_text(encoding="utf-8"),
                css=(SITE / "style.css").read_text(encoding="utf-8"),
                js=(SITE / "app.js").read_text(encoding="utf-8"),
                nav=render_nav(units), main=main_html)
    page = book.resolve_xrefs(page)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}：{len(units) - 1} 个单元，{len(answers)} 道自测题，{len(page.encode()) // 1024} KB")


if __name__ == "__main__":
    main()
