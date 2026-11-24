"""单元七：一个最小的 MCP 服务器，只用标准库。把迷你值班现场的 3 个查询工具，用 MCP 协议提供出去。

传输方式是 stdio：客户端把服务器当子进程启动，每条消息是一行 JSON（JSON-RPC 2.0），写到服务器的标准输入，
服务器把回应写到标准输出。日志只能写标准错误，标准输出只放协议消息。

只实现了跑通工具调用所需的四个方法：initialize、notifications/initialized、tools/list、tools/call（外加 ping）。
真实的服务器建议用官方 SDK；这里手写是为了看清协议本身有多简单。

    python examples/u07_mcp.py     # 由客户端启动它，不需要单独运行
"""
import json
import sys

from mini_world import TOOLS, execute

PROTOCOL_VERSION = "2025-11-25"
MCP_TOOLS = [{"name": t["function"]["name"], "description": t["function"]["description"],
              "inputSchema": t["function"]["parameters"]} for t in TOOLS]


def handle(msg):
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "mini-oncall", "version": "0.1.0"}}
    elif method == "notifications/initialized":
        return None                                   # 通知没有 id，不需要回应
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": MCP_TOOLS}
    elif method == "tools/call":
        p = msg.get("params") or {}
        text = execute(p.get("name"), p.get("arguments") or {})
        result = {"content": [{"type": "text", "text": text}], "isError": text.startswith('{"error"')}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"未知方法 {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


for line in sys.stdin:
    if not line.strip():
        continue
    reply = handle(json.loads(line))
    if reply is not None:
        sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    print(f"[mini-oncall] 处理了 {json.loads(line).get('method')}", file=sys.stderr)
