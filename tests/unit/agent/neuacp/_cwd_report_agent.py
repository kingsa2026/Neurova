import json, os, sys
def send(o):
    sys.stdout.buffer.write((json.dumps(o) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()
while True:
    line = sys.stdin.buffer.readline()
    if not line:
        break
    try:
        msg = json.loads(line.decode("utf-8"))
    except Exception:
        continue
    if msg.get("method") == "initialize":
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {
            "protocolVersion": msg["params"]["protocolVersion"],
            "agentCapabilities": {}}})
        send({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": "s1", "update": {"sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": os.getcwd()}}}})
    elif msg.get("id") is not None:
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
