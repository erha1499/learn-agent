"""单元七 · MCP 到底在传什么？一个最小的 MCP 客户端，连上 mini_mcp_server.py，让 Agent 通过它查 S4。

步骤：
  1. 把服务器作为子进程启动（stdio 传输）
  2. initialize：双方报上协议版本和能力；客户端再发一个 notifications/initialized
  3. tools/list：拿到工具列表，转成模型接口要的格式（name / description / inputSchema → parameters）
  4. 跑单元三的循环：模型要调工具时，客户端发 tools/call，把返回的文字交给模型
全程记下每一条 JSON-RPC 消息。

    python examples/u07_mcp.py            # 真调模型（约 4 次）
    python examples/u07_mcp.py --replay
"""
import json
import os
import subprocess
import sys

from _llm import replay_or_run
from mini_agent import run_agent
from mini_world import SCENARIOS, SYSTEM, verdict

HERE = os.path.dirname(os.path.abspath(__file__))


class MCPClient:
    def __init__(self, cmd):
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, encoding="utf-8")
        self.next_id, self.log = 1, []

    def _send(self, msg):
        self.log.append({"dir": "→", "msg": msg})
        self.p.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.p.stdin.flush()

    def request(self, method, params=None):
        mid, self.next_id = self.next_id, self.next_id + 1
        self._send({"jsonrpc": "2.0", "id": mid, "method": method, **({"params": params} if params is not None else {})})
        while True:                                   # 读到 id 对得上的那条回应为止
            reply = json.loads(self.p.stdout.readline())
            self.log.append({"dir": "←", "msg": reply})
            if reply.get("id") == mid:
                if "error" in reply:
                    raise RuntimeError(reply["error"])
                return reply["result"]

    def notify(self, method):
        self._send({"jsonrpc": "2.0", "method": method})

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=5)


def run():
    c = MCPClient([sys.executable, os.path.join(HERE, "mini_mcp_server.py")])
    c.request("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                             "clientInfo": {"name": "learn-agent-mini-client", "version": "0.1.0"}})
    c.notify("notifications/initialized")
    listed = c.request("tools/list")["tools"]
    tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["inputSchema"]}}
             for t in listed]

    def call_tool(name, args):
        res = c.request("tools/call", {"name": name, "arguments": args})
        return "\n".join(x["text"] for x in res["content"] if x["type"] == "text")

    s = SCENARIOS["S4"]
    a = run_agent(s["question"], SYSTEM, tools, call_tool, seed=1)
    c.close()
    return {"log": c.log, "pred": verdict(a["answer"]), "gold": s["gold"], "turns": len(a["trace"])}


r = replay_or_run("u07_mcp", run)
for x in r["log"]:
    text = json.dumps(x["msg"], ensure_ascii=False)
    print(x["dir"], text if len(text) <= 160 else text[:157] + "...")
print(f"\nAgent 通过 MCP 调工具，{r['turns']} 轮，结论 {r['pred']}（标准答案 {r['gold']}）")
print(f"模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
