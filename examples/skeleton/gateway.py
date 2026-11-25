"""模型网关：每一次模型调用都经过这里，重试只在这一处做（单元十二）。

    并发上限   一个信号量，按上游的限额定；超出的调用在这里排队，而不是去撞上游的 429
    重试       只重试限流（429）、服务端错误（5xx）和连接错误；有 retry-after 就按它等，没有就指数退避加随机抖动
    用量       记下成功调用、尝试次数、限流次数、token
"""
import json
import os
import random
import threading
import time
import urllib.error
import urllib.request

import _llm


class RateLimited(Exception):
    def __init__(self, retry_after=None):
        super().__init__("429")
        self.retry_after = retry_after


class Transient(Exception):
    pass


def http_backend(messages, model, tools=None, **params):
    """发一次请求，不重试。示例客户端 _llm.chat 自带重试，再套进网关就成了两层重试，所以这里直接发。"""
    body = {"model": model, "messages": messages, **params}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(_llm.BASE + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', '')}"})
    try:
        return _llm._send(req, False)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            ra = e.headers.get("retry-after")
            raise RateLimited(float(ra) if ra else None)
        if e.code >= 500:
            raise Transient(str(e.code))
        raise
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        raise Transient(str(e))


class Gateway:
    def __init__(self, backend=http_backend, concurrency=4, max_retries=4, base_delay=1.0, cap=30.0, seed=0):
        self.backend, self.max_retries, self.base, self.cap = backend, max_retries, base_delay, cap
        self.sem, self.lock, self.rng = threading.Semaphore(concurrency), threading.Lock(), random.Random(seed)
        self.stats = {"calls": 0, "attempts": 0, "rate_limited": 0, "errors": 0, "input_tokens": 0, "output_tokens": 0}

    def _add(self, **kw):
        with self.lock:
            for k, v in kw.items():
                self.stats[k] += v

    def _backoff(self, attempt):
        with self.lock:
            return self.rng.uniform(0, min(self.cap, self.base * 2 ** attempt))

    def call(self, **kw):
        delay = 0.0
        for attempt in range(self.max_retries + 1):
            if delay:
                time.sleep(delay)
            with self.sem:
                self._add(attempts=1)
                try:
                    r = self.backend(**kw)
                except RateLimited as e:
                    self._add(rate_limited=1)
                    delay = e.retry_after or self._backoff(attempt)
                    continue
                except Transient:
                    self._add(errors=1)
                    delay = self._backoff(attempt)
                    continue
            u = r.get("usage", {})
            self._add(calls=1, input_tokens=u.get("prompt_tokens", 0), output_tokens=u.get("completion_tokens", 0))
            return r
        raise RuntimeError(f"模型调用试了 {self.max_retries + 1} 次都没成功")
