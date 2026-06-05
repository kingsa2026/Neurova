"""
Neurova 密码加密工具

使用 bcrypt 进行密码加密和验证
"""

import typing
import logging

import bcrypt
import secrets

logger = logging.getLogger(__name__)


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
        logger.info("PasswordHasher initialized with rounds=%d", rounds)
    
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
        
        try:
            # 生成盐并哈希密码
            salt = bcrypt.gensalt(rounds=self.rounds)
            hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
            return hashed.decode('utf-8')
            
        except Exception as e:
            logger.error("Failed to hash password: %s", e)
            raise
    
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
        
        try:
            # 验证密码
            return bcrypt.checkpw(
                password.encode('utf-8'),
                hashed_password.encode('utf-8')
            )
            
        except Exception as e:
            logger.error("Failed to verify password: %s", e)
            return False
    
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
            password = ''.join(secrets.choice(characters) for _ in range(length))
            
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
            "feedback": []
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


def get_password_hasher() -> PasswordHasher:
    """
    获取密码哈希器实例（单例模式）
    
    Returns:
        PasswordHasher实例
    """
    global _password_hasher
    if _password_hasher is None:
        _password_hasher = PasswordHasher()
    return _password_hasher


def reset_password_hasher():
    """
    重置密码哈希器实例（用于测试）
    """
    global _password_hasher
    _password_hasher = None