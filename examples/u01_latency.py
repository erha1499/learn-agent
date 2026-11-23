"""单元一 · 时延：首字时间和总时间分别由什么决定？

同一个模型，一次只要几个字，一次要几百字，流式调用，记"第一个字到达"和"全部收完"的时间。

    python examples/u01_latency.py            # 真调模型（各 3 次）
    python examples/u01_latency.py --replay
"""
from _llm import chat, replay_or_run

SHORT = "用一句话说明什么是数据库连接池。"
LONG = "详细说明数据库连接池的原理、关键参数（至少 6 个）和常见故障，写 500 字左右。"


def run():
    out = {}
    for name, p in (("短回答", SHORT), ("长回答", LONG)):
        out[name] = []
        for _ in range(3):
            r = chat([{"role": "user", "content": p}], stream=True, temperature=0.3)
            out[name].append({"ttft": r["ttft"], "total": r["latency"], "out_tokens": r["usage"].get("completion_tokens"),
                              "in_tokens": r["usage"].get("prompt_tokens")})
    return out


r = replay_or_run("u01_latency", run)
print(f"{'':<6}{'输出 token':>10}{'首字时间':>10}{'总时间':>10}{'生成速度':>12}")
for name, xs in r.items():
    if name.startswith("_"):
        continue
    for x in xs:
        speed = x["out_tokens"] / max(0.001, x["total"] - x["ttft"])
        print(f"{name:<6}{x['out_tokens']:>10}{x['ttft']:>9.2f}s{x['total']:>9.2f}s{speed:>9.0f} tok/s")
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测（受网络和服务端负载影响，看量级）")
