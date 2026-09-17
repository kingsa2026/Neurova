"""
Neurova 密码加密工具

优先使用 bcrypt 进行密码加密和验证；bcrypt 缺席时降级到 PBKDF2-SHA256
（与 neurova/api/auth.py 的 hash_password 同一降级策略与同一哈希格式）。

被降级的原因（CI 实测）：e2e job 按设计只装最小 import 面
（requirements.txt --no-deps + fastapi/uvicorn/...），而 passlib[bcrypt] 的
bcrypt extra 在 --no-deps 下不会被解析，bcrypt 必然缺席。此前本模块在
模块级硬 `import bcrypt`，导致 tests/e2e/conftest.py 收集即 ImportError，
boot 冒烟整条流水线在"还没启动后端"时就红（exit 4）。模块级硬导入与
"CI 精简依赖"这一前提直接冲突，故改为模块级可选导入 + 调用点降级。
"""

from neurova.core.logger import get_logger
import base64
import hashlib
import secrets
import typing

try:  # bcrypt 为可选依赖：缺席时降级 PBKDF2，不阻断导入
    import bcrypt

    BCRYPT_AVAILABLE = True
except ImportError:  # pragma: no cover - 精简 CI 环境走此分支
    bcrypt = None  # type: ignore[assignment]
    BCRYPT_AVAILABLE = False

logger = get_logger(__name__)

# PBKDF2 降级参数（与 neurova/api/auth.py 保持同格式同强度，可互认）
PBKDF2_ITERATIONS = 260000
PBKDF2_ALGO = "pbkdf2:sha256"


class PasswordHasher:
    """
    密码哈希器
    使用 bcrypt 算法进行密码哈希和验证
    """

    def __init__(self, rounds: int = 12):
        """
        初始化密码哈希器

        Args:
            rounds: bcrypt 的轮数，值越大越安全但越慢（默认12）
        """
        self.rounds = rounds
        logger.info(
            "PasswordHasher initialized with rounds=%d, backend=%s",
            rounds,
            "bcrypt" if BCRYPT_AVAILABLE else "pbkdf2",
        )

    def hash_password(self, password: str) -> str:
        """
        哈希密码

        Args:
            password: 明文密码

        Returns:
            哈希后的密码字符串

        Raises:
            ValueError: 如果密码为空
        """
        if not password:
            raise ValueError("Password cannot be empty")

        if BCRYPT_AVAILABLE:
            try:
                # 生成盐并哈希密码
                salt = bcrypt.gensalt(rounds=self.rounds)
                hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
                return hashed.decode("utf-8")
            except Exception as e:
                logger.error("Failed to hash password: %s", e)
                raise

        # bcrypt 缺席：降级 PBKDF2-SHA256（带随机盐，NIST 推荐 KDF）
        logger.warning("bcrypt 不可用，降级使用 PBKDF2-SHA256 哈希密码")
        salt = secrets.token_bytes(16)
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations=PBKDF2_ITERATIONS
        )
        return (
            f"{PBKDF2_ALGO}:{PBKDF2_ITERATIONS}:"
            f"{base64.b64encode(salt).decode()}:{base64.b64encode(dk).decode()}"
        )

    def verify_password(self, password: str, hashed_password: str) -> bool:
        """
        验证密码

        Args:
            password: 明文密码
            hashed_password: 哈希后的密码

        Returns:
            密码是否匹配

        Raises:
            ValueError: 如果密码或哈希密码为空
        """
        if not password or not hashed_password:
            raise ValueError("Password and hashed password cannot be empty")

        if BCRYPT_AVAILABLE:
            try:
                # 验证密码
                return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
            except ValueError:
                # 不是 bcrypt 哈希格式（如 PBKDF2 产物）→ 落到下方统一校验
                pass
            except Exception as e:
                logger.error("Failed to verify password: %s", e)
                return False

        # bcrypt 缺席或哈希非 bcrypt 格式：走 PBKDF2-SHA256 校验
        return self._verify_pbkdf2(password, hashed_password)

    @staticmethod
    def _verify_pbkdf2(password: str, hashed_password: str) -> bool:
        """校验 PBKDF2-SHA256 哈希（格式 pbkdf2:sha256:<iters>:<salt_b64>:<dk_b64>）。

        未知/无盐格式一律拒绝——不静默回退到弱哈希。
        """
        if not hashed_password.startswith(PBKDF2_ALGO + ":"):
            return False
        parts = hashed_password.split(":")
        if len(parts) != 5:
            return False
        _, _, iterations_b64, salt_b64, dk_b64 = parts
        try:
            iterations = int(iterations_b64)
            salt = base64.b64decode(salt_b64)
            expected = base64.b64decode(dk_b64)
        except (ValueError, TypeError) as e:
            logger.error("Failed to parse PBKDF2 hash: %s", e)
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations=iterations
        )
        return secrets.compare_digest(dk, expected)

    def generate_random_password(self, length: int = 16) -> str:
        """
        生成随机密码

        Args:
            length: 密码长度（默认16）

        Returns:
            随机密码字符串

        Raises:
            ValueError: 如果长度小于8
        """
        if length < 8:
            raise ValueError("Password length must be at least 8 characters")

        try:
            # 使用 secrets 模块生成安全随机密码
            # 包含大小写字母、数字和特殊字符
            import string

            characters = string.ascii_letters + string.digits + "!@#$%^&*"
            password = "".join(secrets.choice(characters) for _ in range(length))

            # 确保密码包含至少一个大写字母、一个小写字母、一个数字和一个特殊字符
            has_upper = any(c.isupper() for c in password)
            has_lower = any(c.islower() for c in password)
            has_digit = any(c.isdigit() for c in password)
            has_special = any(c in "!@#$%^&*" for c in password)

            if not (has_upper and has_lower and has_digit and has_special):
                # 重新生成直到满足要求
                return self.generate_random_password(length)

            return password

        except Exception as e:
            logger.error("Failed to generate random password: %s", e)
            raise

    def is_password_strong(self, password: str) -> bool:
        """
        检查密码强度

        Args:
            password: 明文密码

        Returns:
            密码是否足够强
        """
        if len(password) < 8:
            return False

        has_upper = any(c.isupper() for c in password)
        has_lower = any(c.islower() for c in password)
        has_digit = any(c.isdigit() for c in password)
        has_special = any(c in "!@#$%^&*()_+-=[]{}|;':\",./<>?" for c in password)

        return has_upper and has_lower and has_digit and has_special

    def get_password_strength(self, password: str) -> dict:
        """
        获取密码强度详情

        Args:
            password: 明文密码

        Returns:
            密码强度详情字典
        """
        strength = {
            "length": len(password),
            "has_upper": any(c.isupper() for c in password),
            "has_lower": any(c.islower() for c in password),
            "has_digit": any(c.isdigit() for c in password),
            "has_special": any(c in "!@#$%^&*()_+-=[]{}|;':\",./<>?" for c in password),
            "is_strong": False,
            "score": 0,
            "feedback": [],
        }

        # 计算分数
        score = 0
        if strength["length"] >= 8:
            score += 1
        if strength["length"] >= 12:
            score += 1
        if strength["length"] >= 16:
            score += 1
        if strength["has_upper"]:
            score += 1
        if strength["has_lower"]:
            score += 1
        if strength["has_digit"]:
            score += 1
        if strength["has_special"]:
            score += 1

        strength["score"] = score
        strength["is_strong"] = score >= 5

        # 提供反馈
        if strength["length"] < 8:
            strength["feedback"].append("Password should be at least 8 characters long")
        if not strength["has_upper"]:
            strength["feedback"].append("Password should contain at least one uppercase letter")
        if not strength["has_lower"]:
            strength["feedback"].append("Password should contain at least one lowercase letter")
        if not strength["has_digit"]:
            strength["feedback"].append("Password should contain at least one digit")
        if not strength["has_special"]:
            strength["feedback"].append("Password should contain at least one special character")

        return strength


# 全局实例
_password_hasher: typing.Optional[PasswordHasher] = None
_password_hasher_lock = __import__('threading').Lock()


def get_password_hasher() -> PasswordHasher:
    """
    获取密码哈希器实例（单例模式）

    Returns:
        PasswordHasher实例
    """
    global _password_hasher
    if _password_hasher is None:
        with _password_hasher_lock:
            if _password_hasher is None:
                _password_hasher = PasswordHasher()
    return _password_hasher


def reset_password_hasher():
    """
    重置密码哈希器实例（用于测试）
    """
    global _password_hasher
    _password_hasher = None
