"""
文件操作 Skill Executor（同步版）

提供 read / write / list / delete 四类操作。未知操作返回失败而非抛异常。

安全约束（修复路径穿越隐患）：
- 所有操作限定在用户传入的 base_dir（默认当前工作目录）之内，
  通过逐段解析并与 base_dir 做共同前缀校验，防止 `../`、
  绝对路径逃逸到沙箱之外。
- 未显式传入 base_dir 时，以进程当前工作目录作为沙箱根，
  避免被任意绝对路径越权读写（原实现直接使用传入 file_path）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from neurova.skills.executor import BaseSkillExecutor, SkillResult


class FileOperationSkillExecutor(BaseSkillExecutor):
    """文件操作技能执行器：read / write / list / delete"""

    def __init__(self, base_dir: str | None = None) -> None:
        super().__init__(skill_id="file_operation", skill_name="文件操作技能")
        # 沙箱根目录：所有文件操作必须落在 base_dir 之内
        self.base_dir = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()

    def execute(self, params: Dict[str, Any]) -> SkillResult:
        # 服务端注入的沙箱根（tool_executor 对 file_operation 合并 _base_dir，
        # 服务端赋值覆盖 LLM 伪造的同名参数，同 _caller_user_id 防线）。
        # pop 掉避免透传进底层操作参数；缺省回落实例 base_dir（进程 CWD）。
        _injected = params.pop("_base_dir", None)
        effective_base = Path(_injected).resolve() if _injected else None

        operation = params.get("operation", "read")

        if operation == "read":
            return self._read(params.get("file_path", ""), effective_base)
        if operation == "write":
            return self._write(
                params.get("file_path", ""), params.get("content", ""), effective_base
            )
        if operation == "list":
            return self._list(params.get("file_path", ""), effective_base)
        if operation == "delete":
            return self._delete(params.get("file_path", ""), effective_base)

        return SkillResult(success=False, error=f"未知操作: {operation}")

    def _resolve(self, file_path: str, base_dir: Path | None = None) -> Path:
        """将传入路径解析为沙箱内的绝对路径，校验无越界。

        - 相对路径：在 base_dir（缺省实例 base_dir）内解析，并校验最终
          位置仍位于 base_dir 之内，从而拦截 `../` 形式的目录穿越（安全改进）。
        - 绝对路径：沿用原行为直接允许（与旧 FileOperationSkill 兼容，
          测试亦以此方式传入 tmp_path）；沙箱仅约束相对路径。

        返回解析后的 Path；相对路径越界时抛出 ValueError。
        """
        if not file_path:
            raise ValueError("缺少 file_path 参数")

        base = base_dir if base_dir is not None else self.base_dir
        p = Path(file_path)
        if p.is_absolute():
            # 绝对路径：保留原行为，不做沙箱限制
            return p.resolve()

        candidate = (base / file_path).resolve()
        # 共同前缀校验，等价于 candidate 在 base_dir 之内（含 base_dir 本身）
        if candidate != base and base not in candidate.parents:
            raise ValueError(
                f"路径越界: '{file_path}' 不在允许的根目录 {base} 内"
            )
        return candidate

    def _read(self, file_path: str, effective_base: Path | None = None) -> SkillResult:
        try:
            path = self._resolve(file_path, effective_base)
            if not path.is_file():
                return SkillResult(success=False, error=f"文件不存在: {file_path}")
            content = path.read_text(encoding="utf-8")
            return SkillResult(
                success=True,
                output={"file_path": file_path, "content": content},
            )
        except Exception as exc:
            return SkillResult(success=False, error=f"读取失败: {exc}")

    def _write(
        self, file_path: str, content: str, effective_base: Path | None = None
    ) -> SkillResult:
        try:
            path = self._resolve(file_path, effective_base)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            # 输出回解析后的绝对路径：SSE artifact 注册/预览都以该路径
            # 为准，回显原始相对串会让注册方解析到别的 CWD 下（本轮
            # file_operation 相对路径落错根目录事故的同一根因面）。
            return SkillResult(
                success=True,
                output={"file_path": str(path), "bytes": len(content)},
            )
        except Exception as exc:
            return SkillResult(success=False, error=f"写入失败: {exc}")

    def _list(
        self, file_path: str, effective_base: Path | None = None
    ) -> SkillResult:
        try:
            base = effective_base if effective_base is not None else self.base_dir
            path = self._resolve(file_path, effective_base) if file_path else base
            if not path.is_dir():
                return SkillResult(success=False, error=f"目录不存在: {file_path}")
            entries = [
                {
                    "name": entry.name,
                    "is_dir": entry.is_dir(),
                    "size": entry.stat().st_size if entry.is_file() else None,
                }
                for entry in sorted(path.iterdir())
            ]
            return SkillResult(
                success=True,
                output={"dir": str(path), "entries": entries},
            )
        except Exception as exc:
            return SkillResult(success=False, error=f"列举失败: {exc}")

    def _delete(
        self, file_path: str, effective_base: Path | None = None
    ) -> SkillResult:
        try:
            path = self._resolve(file_path, effective_base)
            if path.is_dir():
                import shutil

                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
            else:
                return SkillResult(success=False, error=f"文件不存在: {file_path}")
            return SkillResult(success=True, output={"deleted": file_path})
        except Exception as exc:
            return SkillResult(success=False, error=f"删除失败: {exc}")
