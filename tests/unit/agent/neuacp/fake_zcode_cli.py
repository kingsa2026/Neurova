# -*- coding: utf-8 -*-
"""测试内假 ZCode CLI：模拟插件形态的 stream-json NDJSON 输出。

FAKE_ZCODE_MODE：
  ok        system → assistant(text) → result 正常收官
  no_result system → assistant 后不发 result、正常退出 0（F3 保真：无 result 帧=诚实失败）
  fail      中途非零退出（exit 2）
  garbage   推送无法解析的行后再正常收官（容错要求）
  thinking  assistant 事件里带 thinking 块（映射 reasoning）
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
    if mode == "no_result":
        # F3 拍板 D-B：runtime 未报告 result 帧、退出码 0——执行体必须诚实失败，
        # 不得用累积 chunk 拼接冒充结果。
        sys.stdout.flush()
        sys.exit(0)
    if mode == "fail":
        sys.exit(2)
    if mode == "garbage":
        sys.stdout.buffer.write(b"not-a-json-line\n")
        sys.stdout.flush()
    send({"type": "result", "result": "答案正文", "is_error": False})


if __name__ == "__main__":
    main()
