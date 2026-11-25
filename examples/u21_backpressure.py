"""单元二十一 · 排队，还是去撞上游的限流？离散事件模拟，不调模型，固定种子可复现。

场景：一次故障让 100 个人同时来问（告警风暴）。每个任务要顺序调 4 次模型，两次之间查一次工具（0.3 秒）。
模型服务同时只接 8 个请求，第 9 个直接返回 429。单次调用耗时取对数正态分布，中位数 1.7 秒（接近单元十二实测的 p50）。
同一次调用最多重试 5 次，还失败，这个任务就算失败。五种做法：

  P1 不排队，429 了立刻重试
  P2 不排队，429 了指数退避加随机抖动（1、2、4……秒，上限 30 秒）
  P3 排队，worker 数 = 8，等于上游的并发上限
  P4 排队，worker 数 = 16，上限的两倍，429 了指数退避
  P5 排队，worker 数 = 4，上限的一半

每种做法换 20 个随机种子各跑一遍，报平均。

    python examples/u21_backpressure.py
"""
import heapq
import itertools
import math
import random
import statistics as st
from collections import deque

JOBS, CAP, CALLS, TOOL_S, MEDIAN, SIGMA, MAX_RETRIES, SEEDS = 100, 8, 4, 0.3, 1.7, 0.25, 5, 20
POLICIES = {
    "P1 不排队，立刻重试": (None, "now"),
    "P2 不排队，退避重试": (None, "backoff"),
    "P3 排队，worker = 8": (8, "backoff"),
    "P4 排队，worker = 16": (16, "backoff"),
    "P5 排队，worker = 4": (4, "backoff"),
}


def delay(kind, tries, rng):
    if kind == "now":
        return rng.uniform(0.05, 0.15)
    return rng.uniform(0, min(30.0, 2.0 ** (tries - 1)))


def simulate(workers, retry, seed):
    rng, order = random.Random(seed), itertools.count()
    events, busy = [], 0
    jobs = [{"step": 0, "tries": 0, "end": None, "failed": False} for _ in range(JOBS)]
    queue, active, limit = deque(range(JOBS)), 0, workers or JOBS
    stats = {"sent": 0, "r429": 0}

    def push(t, kind, j):
        heapq.heappush(events, (t, next(order), kind, j))

    def start(t):
        nonlocal active
        while active < limit and queue:
            active += 1
            push(t, "req", queue.popleft())

    def finish(t, j, failed):
        nonlocal active
        jobs[j].update(end=t, failed=failed)
        active -= 1
        start(t)

    start(0.0)
    while events:
        t, _, kind, j = heapq.heappop(events)
        job = jobs[j]
        if kind == "req":
            stats["sent"] += 1
            if busy < CAP:
                busy += 1
                push(t + rng.lognormvariate(math.log(MEDIAN), SIGMA), "resp", j)
            else:
                stats["r429"] += 1
                job["tries"] += 1
                if job["tries"] > MAX_RETRIES:
                    finish(t, j, True)
                else:
                    push(t + delay(retry, job["tries"], rng), "req", j)
        else:
            busy -= 1
            job["step"], job["tries"] = job["step"] + 1, 0
            if job["step"] == CALLS:
                finish(t, j, False)
            else:
                push(t + TOOL_S, "req", j)
    ok = sorted(x["end"] for x in jobs if not x["failed"])
    return {"done": len(ok), "failed": JOBS - len(ok), "sent": stats["sent"], "r429": stats["r429"],
            "p50": ok[len(ok) // 2] if ok else float("nan"), "p95": ok[int(len(ok) * .95) - 1] if ok else float("nan"),
            "makespan": max(x["end"] for x in jobs)}


print(f"{JOBS} 个任务同时到达，每个调 {CALLS} 次模型；上游同时只接 {CAP} 个请求；每种做法 {SEEDS} 个种子取平均\n")
print(f"  {'做法':<18}{'完成':>6}{'失败':>6}{'发出的请求':>10}{'其中 429':>9}{'完成时间 p50':>12}{'p95':>8}{'全部结束':>9}")
for name, (w, retry) in POLICIES.items():
    rs = [simulate(w, retry, s) for s in range(SEEDS)]
    m = {k: st.mean(r[k] for r in rs) for k in rs[0]}
    print(f"  {name:<18}{m['done']:>6.1f}{m['failed']:>6.1f}{m['sent']:>10.0f}{m['r429']:>9.0f}"
          f"{m['p50']:>10.1f} 秒{m['p95']:>6.1f} 秒{m['makespan']:>7.1f} 秒")
useful = JOBS * CALLS
print(f"\n每个任务都成功时，有用的请求是 {useful} 个；理论上最快 {useful * MEDIAN / CAP:.0f} 秒左右做完"
      f"（{useful} 次 × {MEDIAN} 秒 ÷ {CAP} 个并发，不算工具时间和耗时的波动）")
