"""单元十五 · 给打分器写单元测试。不调模型。

打分器也是代码，也会写错。做法和测普通函数一样：准备一批“回答 + 标准答案 + 应该判对还是判错”，
看每个打分器判得对不对。下面 8 条回答是按真实运行里见过的写法改出来的。

    python examples/u15_grader_tests.py
"""
import re

from u15_graders import KEYWORDS
from mini_world import verdict

TESTS = [
    ("连接数 1000/1000，错误日志里有 Too many connections。\n\n根因: MAX_CONNECTIONS", "MAX_CONNECTIONS", True, "标准格式"),
    ("错误日志里是 errno 28。\n\n根因：**DISK_FULL**", "DISK_FULL", True, "全角冒号、加粗"),
    ("错误日志里是 errno 28。\n\n根因: disk_full", "DISK_FULL", True, "编号写成小写"),
    ("根因: DISK_FULL（磁盘写满），建议先清理 binlog。", "DISK_FULL", True, "编号后面跟着解释"),
    ("先看像网络问题，根因: NETWORK。再看错误日志，更正：根因: DISK_FULL", "DISK_FULL", True, "中途改口，以最后一个为准"),
    ("磁盘使用率正常，排除磁盘写满；Lock wait timeout 很多。\n\n根因: LOCK_WAIT", "DISK_FULL", False, "提到了正确答案，但是排除了它"),
    ("可能是 DISK_FULL，也可能是 LOCK_WAIT，需要进一步确认。", "DISK_FULL", False, "两头下注，没给结论"),
    ("网络检查正常，丢包率 0。\n\n根因: SLOW_SQL", "NETWORK", False, "关键词出现在“正常”的描述里"),
]


def strict(text, cause):
    return verdict(text) == cause


def loose(text, cause):
    return cause in text or any(k in text for k in KEYWORDS[cause])


def strict_v2(text, cause):
    """先规整再比较：编号转大写；只认最后一个“根因:”。"""
    found = re.findall(r"根因\s*[:：]\s*\**\s*([A-Za-z_]+)", text or "")
    return bool(found) and found[-1].upper() == cause


for name, g in [("结论·严格", strict), ("结论·宽松", loose), ("结论·严格（规整后）", strict_v2)]:
    wrong = [note for text, cause, want, note in TESTS if g(text, cause) != want]
    print(f"{name}：{len(TESTS) - len(wrong)}/{len(TESTS)} 判对" + (f"，判错的：{'；'.join(wrong)}" if wrong else ""))
