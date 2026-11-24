"""单元十二 · 一次模型调用要多久？同一个请求发 30 次，看延迟的分布，而不是平均值。

请求固定：“用一句话解释什么是数据库连接池”，max_tokens=60。
  A. 顺序发 30 次
  B. 10 个线程并发，共发 30 次
记下每次的总耗时，算 p50、p90、p95、最大值，以及失败次数。网关的超时、重试、并发上限，都要按这些数来定。

    python examples/u12_latency.py            # 真调模型（60 次很短的调用）
    python examples/u12_latency.py --replay
"""
import time
from concurrent.futures import ThreadPoolExecutor

from _llm import chat, replay_or_run

MSG = [{"role": "user", "content": "用一句话解释什么是数据库连接池"}]


def call(_):
    t0 = time.time()
    try:
        r = chat(MSG, max_tokens=60)
        return {"ok": True, "seconds": round(time.time() - t0, 3), "out": r["usage"].get("completion_tokens", 0)}
    except Exception as e:  # noqa: BLE001  记录失败，不中断统计
        return {"ok": False, "seconds": round(time.time() - t0, 3), "error": type(e).__name__}


def run():
    seq = [call(i) for i in range(30)]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=10) as pool:
        par = list(pool.map(call, range(30)))
    return {"sequential": seq, "concurrent": par, "concurrent_wall": round(time.time() - t0, 2)}


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


r = replay_or_run("u12_latency", run)
for k, label in (("sequential", "A. 顺序 30 次"), ("concurrent", "B. 10 并发共 30 次")):
    ok = [x["seconds"] for x in r[k] if x["ok"]]
    print(f"{label}：成功 {len(ok)}/30，p50 {pct(ok, .5):.2f} 秒，p90 {pct(ok, .9):.2f}，p95 {pct(ok, .95):.2f}，"
          f"最大 {max(ok):.2f}，最小 {min(ok):.2f}")
print(f"顺序 30 次合计 {sum(x['seconds'] for x in r['sequential']):.1f} 秒；并发 30 次墙钟 {r['concurrent_wall']} 秒")
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
