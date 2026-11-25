"""灰度和回滚（单元二十二）。

    route        按会话 ID 的哈希把一部分新会话分给灰度版本；同一个会话永远落在同一边
    repin_queued 回滚时，排队中还没开始的任务改回稳定版本；已经在跑的任务跑完它自己的版本
"""
import hashlib


def route(session_id, stable, canary=None, pct=0):
    if not canary or pct <= 0:
        return stable
    h = int(hashlib.sha256(session_id.encode()).hexdigest()[:8], 16) % 100
    return canary if h < pct else stable


def repin_queued(store, old, new):
    with store.db() as db:
        cur = db.execute("UPDATE jobs SET config_id = ? WHERE status = 'queued' AND config_id = ?", (new, old))
        return cur.rowcount
