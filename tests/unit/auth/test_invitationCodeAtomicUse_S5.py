"""P2 §3.5-13 红灯：邀请码/验证码 read-then-write 非原子。

- invitation_code.use_code：get_code 读 current_uses → can_be_used 判定 →
  用**陈旧读数**回写 UPDATE——并发下 max_uses=1 邀请码可被双人同时使用。
  修复判据：改单条条件 UPDATE（`current_uses < max_uses` 进 WHERE），
  rowcount 决定成败，失败方拒绝。
- verification_code.verify_code：读 is_valid → _mark_as_used 无条件 UPDATE
  `SET is_used = 1`——并发验证双双放行。修复判据：条件 UPDATE
  `WHERE is_used = 0`，rowcount=0 即已被他人核销，返回 False。
"""

import threading

import pytest

from neurova.auth.invitation_code import InvitationCodeModel, InvitationCodeType
from neurova.auth.verification_code import VerificationCodeModel, VerificationType


def _runTwo(fn_a, fn_b):
    results = {"a": None, "b": None}

    def _wrap(key, fn):
        def _inner():
            results[key] = fn()
        return _inner

    ta = threading.Thread(target=_wrap("a", fn_a))
    tb = threading.Thread(target=_wrap("b", fn_b))
    ta.start()
    tb.start()
    ta.join(timeout=10)
    tb.join(timeout=10)
    return results


def test_single_use_invitation_code_concurrent_use_only_once(tmp_path, monkeypatch):
    model = InvitationCodeModel(db_path=str(tmp_path / "inv.db"))
    invitation = model.create_code(
        code_type=InvitationCodeType.SINGLE_USE,
        max_uses=1,
        expires_in=600,
        created_by="s5-test",
    )
    code = invitation.code

    # 屏障钉在「读取完成之后、写回之前」：两线程都拿到同一陈旧读数再放行
    realGetCode = model.get_code
    barrier = threading.Barrier(2)

    def barrierGetCode(c):
        record = realGetCode(c)
        if record is not None:
            try:
                barrier.wait(timeout=2.0)
            except threading.BrokenBarrierError:
                pass  # 绿（条件 UPDATE 串行）路径：第二读进不来则超时放行
        return record

    monkeypatch.setattr(model, "get_code", barrierGetCode)

    results = _runTwo(
        lambda: model.use_code(code, "userA"),
        lambda: model.use_code(code, "userB"),
    )

    winners = [r for r in results.values() if r is not None]
    assert len(winners) == 1, (
        f"max_uses=1 邀请码被并发使用 {len(winners)} 次（read-then-write 非原子）"
    )
    row = realGetCode(code)
    assert row.current_uses == 1, f"current_uses 落库值 {row.current_uses} ≠ 1"


def test_verification_code_concurrent_verify_only_once(tmp_path, monkeypatch):
    model = VerificationCodeModel(db_path=str(tmp_path / "vc.db"))
    target = "s5@example.com"
    code = model.create_code(target=target, code_type=VerificationType.REGISTER, expires_in=300)

    # 屏障钉在 hash 校验后、核销前：两线程都通过有效性检查再放行
    realHash = model._hash_code
    barrier = threading.Barrier(2)

    def barrierHash(c):
        h = realHash(c)
        try:
            barrier.wait(timeout=2.0)
        except threading.BrokenBarrierError:
            pass
        return h

    monkeypatch.setattr(model, "_hash_code", barrierHash)

    results = _runTwo(
        lambda: model.verify_code(target, code, VerificationType.REGISTER, mark_as_used=True),
        lambda: model.verify_code(target, code, VerificationType.REGISTER, mark_as_used=True),
    )

    truths = [v for v in results.values() if v is True]
    assert len(truths) == 1, (
        f"一次性验证码被并发核销通过 {len(truths)} 次（read-then-write 非原子）"
    )
