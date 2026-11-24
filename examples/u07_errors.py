"""单元七 · 工具的报错信息也是提示词：报错写得好不好，模型能不能自己改对？

用户说“订单库”，没给实例名；get_metrics 要的是 order-mysql-01 这样的实例名（参数说明里不给例子）。
模型猜错名字时，工具返回两种报错之一，各跑 5 遍：
  A. 只有错误码：{"error": "404 Not Found"}
  B. 说清原因和下一步：找不到这个实例，实例名长什么样，现有哪些实例、各属于什么业务
记下：最后有没有查到 order-mysql-01、调了几次工具、有没有反问用户。

    python examples/u07_errors.py            # 真调模型（约 30 次）
    python examples/u07_errors.py --replay
"""
import copy
import json

from _llm import replay_or_run
from mini_agent import run_agent
from mini_world import BY_INSTANCE, SYSTEM, TOOLS, execute

Q = "订单库的连接数是不是满了？"
TOOLS_NO_EXAMPLE = copy.deepcopy(TOOLS[:1])
TOOLS_NO_EXAMPLE[0]["function"]["parameters"]["properties"]["instance"]["description"] = "实例名"
KNOWN = "、".join(f"{k}（{v}）" for k, v in [("order-mysql-01", "订单"), ("report-mysql-02", "报表"), ("pay-mysql-03", "支付"),
                                           ("user-mysql-04", "用户"), ("inventory-mysql-05", "库存")])


def make_execute(helpful):
    def ex(name, args):
        if args.get("instance") in BY_INSTANCE:
            return execute(name, args)
        if helpful:
            return json.dumps({"error": f"找不到实例 {args.get('instance')!r}。实例名形如 order-mysql-01。现有实例：{KNOWN}"},
                              ensure_ascii=False)
        return json.dumps({"error": "404 Not Found"})
    return ex


def run():
    out = {}
    for mode in ("bare", "helpful"):
        out[mode] = []
        for seed in range(5):
            a = run_agent(Q, SYSTEM, TOOLS_NO_EXAMPLE, make_execute(mode == "helpful"), max_turns=8, seed=seed)
            insts = [c["args"].get("instance") for t in a["trace"] for c in t["calls"]]
            out[mode].append({"instances": insts, "found": "order-mysql-01" in insts, "tool_calls": len(insts),
                              "answer": (a["answer"] or "")[-160:]})
    return out


r = replay_or_run("u07_errors", run)
for mode, label in (("bare", "A. 只有错误码"), ("helpful", "B. 说清原因和下一步")):
    runs = r[mode]
    print(f"{label}：查到 order-mysql-01 {sum(x['found'] for x in runs)}/5，平均调工具 {sum(x['tool_calls'] for x in runs) / 5:.1f} 次")
    for x in runs:
        print(f"    依次尝试的实例名 {x['instances']}  结尾：{x['answer'][-70:]!r}")
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
