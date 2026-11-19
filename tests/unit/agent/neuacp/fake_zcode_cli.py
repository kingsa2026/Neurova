# -*- coding: utf-8 -*-
"""测试内假 ZCode CLI：模拟插件形态的 stream-json NDJSON 输出。

FAKE_ZCODE_MODE：
  ok       system → assistant(text) → result 正常收官
  fail     中途非零退出（exit 2）
  garbage  推送无法解析的行后再正常收官（容错要求）
  thinking assistant 事件里带 thinking 块（映射 reasoning）
"""
import json
import os
import sys


def send(obj):
    sys.stdout.buffer.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.flush()


def main():
    mode = os.environ.get("FAKE_ZCODE_MODE", "ok")
    send({"type": "system", "subtype": "init", "session_id": "z-1"})
    if mode == "thinking":
        send({"type": "assistant", "message": {"content": [
            {"type": "thinking", "thinking": "先想一下"},
            {"type": "text", "text": "答案正文"},
        ]}})
    else:
        send({"type": "assistant", "message": {"content": [{"type": "text", "text": "答案正文"}]}})
    if mode == "fail":
        sys.exit(2)
    if mode == "garbage":
        sys.stdout.buffer.write(b"not-a-json-line\n")
        sys.stdout.flush()
    send({"type": "result", "result": "答案正文", "is_error": False})


if __name__ == "__main__":
    main()
