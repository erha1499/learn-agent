"""worker 池：每个 worker 循环领任务、执行；执行中每一步续一次租约。

worker 死了（这里用 Crash 模拟），任务停在 running，租约到期后被别的 worker 领走，从事件日志接着跑。
同一个会话同一时间只跑一个任务（领任务时在 SQL 里排除），不同会话并行。
每个任务按它提交时记下的指纹去取配置：发布新版本时，已经在跑和排队中的任务仍用原来的版本（单元二十二）。
"""
import threading
import time

from .runner import Crash, run_job


def run_pool(store, cfg, cid, gateway, execute_for, n_workers, lease_s, fault=None, keep_alive=None):
    """cfg / cid 是默认配置；任务的指纹不同时，从 configs 表取它自己的配置。
    keep_alive：返回 True 时，队列空了也不退出（等新任务进来，比如发布演示里的分批提交）。"""
    crashes, cache = [], {cid: cfg}

    def cfg_for(job):
        if job["config_id"] not in cache:
            cache[job["config_id"]] = store.config(job["config_id"])
        return cache[job["config_id"]]

    def loop(name):
        while store.pending() or (keep_alive and keep_alive()):
            job = store.claim(name, lease_s)
            if job is None:
                time.sleep(0.2)
                continue
            try:
                store.finish(job["job_id"], run_job(job, cfg_for(job), job["config_id"], gateway, store, execute_for(job), lease_s, fault))
            except Crash:
                crashes.append({"job_id": job["job_id"], "worker": name, "at": time.time()})
            except Exception as e:                       # 模型调用重试用完等：记失败，不让一个任务拖住整个池
                store.fail(job["job_id"], repr(e))

    threads = [threading.Thread(target=loop, args=(f"w{i + 1}",)) for i in range(n_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return crashes
