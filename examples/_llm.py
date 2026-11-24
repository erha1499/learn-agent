"""例子共用的最小模型客户端：只用标准库，走 OpenAI 兼容接口（默认阿里云百炼 qwen-plus）。

配置从环境变量读，也可以写在仓库根目录的 .env 里：
    OPENAI_API_KEY=sk-...
    OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1   （默认）
    LLM_MODEL=qwen-plus                                                  （默认）

故意不做缓存：单元一要看的就是"同样的输入，每次调用的结果可能不一样"。
每个例子跑完把真实输出写进 examples/output/<例子名>.json；加 --replay 只读录好的结果、不调模型（没有 key 也能看）。
"""
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "examples", "output")


def _dotenv():
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            k, _, v = line.strip().partition("=")
            if k and v and not k.startswith("#") and k not in os.environ:
                os.environ[k] = v.strip().strip("'\"")


_dotenv()
MODEL = os.environ.get("LLM_MODEL", "qwen-plus")
BASE = os.environ.get("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/")


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def chat(messages, model=None, stream=False, **params):
    """调一次模型。返回 {text, usage, finish_reason, latency, ttft}，非流式时还有 tool_calls 和原始 message。
    ttft = 收到第一个字的时间（流式时才有）。传 tools=[...] 就是工具调用（单元二）。"""
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        sys.exit("没有 OPENAI_API_KEY：在环境变量或仓库根目录的 .env 里配置；或者加 --replay 看录好的结果")
    body = {"model": model or MODEL, "messages": messages, **params}
    if stream:
        body.update(stream=True, stream_options={"include_usage": True})
    req = urllib.request.Request(BASE + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    for attempt in range(6):                       # 网络抖动、限流、5xx：等一会儿重试，最多 6 次
        try:
            return _send(req, stream)
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            code = getattr(e, "code", None)
            if attempt == 5 or (code is not None and code != 429 and code < 500):
                raise
            time.sleep(min(2 ** attempt, 16))


def _send(req, stream):
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=120, context=_ctx()) as r:
        if not stream:
            d = json.loads(r.read())
            c = d["choices"][0]
            msg = c["message"]
            return {"text": msg.get("content") or "", "usage": d.get("usage", {}), "finish_reason": c.get("finish_reason"),
                    "latency": round(time.time() - t0, 3), "ttft": None,
                    "tool_calls": msg.get("tool_calls") or [], "message": msg}
        text, usage, finish, ttft = [], {}, None, None
        for raw in r:
            line = raw.decode().strip()
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            d = json.loads(line[5:])
            if d.get("usage"):
                usage = d["usage"]
            for c in d.get("choices") or []:
                piece = (c.get("delta") or {}).get("content")
                if piece:
                    if ttft is None:
                        ttft = round(time.time() - t0, 3)
                    text.append(piece)
                finish = c.get("finish_reason") or finish
        return {"text": "".join(text), "usage": usage, "finish_reason": finish, "latency": round(time.time() - t0, 3),
                "ttft": ttft}


def host():
    """只记服务商的域名，不记账号专属的子域名。"""
    return ".".join(BASE.split("/")[2].split(".")[-3:])


def replay_or_run(name, run):
    """--replay：读 examples/output/<name>.json；否则调用 run() 拿到结果、写进去。返回结果。"""
    path = os.path.join(OUT, f"{name}.json")
    if "--replay" in sys.argv:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    result = run()
    result["_meta"] = {"model": MODEL, "date": time.strftime("%Y-%m-%d"), "base_url": host()}
    os.makedirs(OUT, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    return result
