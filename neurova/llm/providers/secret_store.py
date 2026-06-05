"""
Secret store with simple XOR obfuscation and JSON persistence.
"""
import base64
import datetime
import hashlib
import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


_PREFIX = "enc:"
_SALT = b"neurova-secret-store-v1"
_SALT_LEGACY = b"neurova-secret-store-legacy"
_VERSION_BYTE = 0x01
_DEFAULT_PATH = "./data/secrets.json"
_ITERATIONS = 10000


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}" if prefix else uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _coerce_master(master_key: Any) -> str:
    if master_key is None:
        return ""
    if isinstance(master_key, bytes):
        try:
            return master_key.decode("utf-8")
        except Exception:
            return master_key.hex()
    return str(master_key)


def _derive_key_simple(master_key: str = "", salt: bytes = b"") -> bytes:
    mk = _coerce_master(master_key).encode("utf-8")
    hk = hashlib.sha256()
    hk.update(salt if salt else b"\x00")
    hk.update(mk)
    hk.update(b"|neurova|secret|v1")
    return hk.digest()


def _derive_key_legacy(master_key: str = "", salt: bytes = b"") -> bytes:
    mk = _coerce_master(master_key).encode("utf-8")
    hk = hashlib.sha256()
    hk.update(salt if salt else b"\x00")
    hk.update(mk)
    hk.update(b"|neurova|legacy")
    return hk.digest()


def _derive_key(master_key: str = "") -> bytes:
    return _derive_key_simple(master_key, salt=_SALT)


def _xor_encrypt(plaintext: bytes, key: bytes) -> bytes:
    if not key:
        return bytes(plaintext)
    klen = len(key)
    out = bytearray(len(plaintext))
    for i, b in enumerate(plaintext):
        out[i] = b ^ key[i % klen]
    return bytes(out)


def _try_decode_b64(payload: str) -> bytes:
    try:
        padded = payload + "=" * (-len(payload) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except Exception:
        try:
            return base64.b64decode(payload.encode("ascii"), validate=False)
        except Exception as exc:
            raise ValueError(f"invalid base64 payload: {exc}") from exc


def encrypt_api_key(plaintext: str, master_key: str = "") -> str:
    if plaintext is None or plaintext == "":
        raise ValueError("plaintext must be a non-empty string")
    if not isinstance(plaintext, str):
        plaintext = str(plaintext)
    mk = _coerce_master(master_key)
    key = _derive_key(mk)
    data = bytes([_VERSION_BYTE]) + plaintext.encode("utf-8")
    enc = _xor_encrypt(data, key)
    return _PREFIX + base64.urlsafe_b64encode(enc).decode("ascii")


def _decrypt_with_key(payload: bytes, key: bytes) -> str:
    dec = _xor_encrypt(payload, key)
    if not dec or dec[0] != _VERSION_BYTE:
        raise ValueError("decryption failed: invalid version marker")
    try:
        return dec[1:].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"decryption failed: invalid utf-8: {exc}") from exc


def decrypt_api_key(encrypted: Any, master_key: str = "") -> str:
    if encrypted is None:
        return ""
    if not isinstance(encrypted, str):
        try:
            encrypted = str(encrypted)
        except Exception:
            return ""
    if not encrypted.startswith(_PREFIX):
        return encrypted
    payload = encrypted[len(_PREFIX):]
    try:
        raw = _try_decode_b64(payload)
    except Exception:
        raise ValueError("encrypted payload is not valid base64")
    mk = _coerce_master(master_key)
    try:
        return _decrypt_with_key(raw, _derive_key(mk))
    except Exception:
        try:
            return _decrypt_with_key(raw, _derive_key_legacy(mk, salt=_SALT_LEGACY))
        except Exception as exc:
            raise ValueError(f"decryption failed: {exc}") from exc


class SecretStore:
    def __init__(
        self,
        master_key: str = "",
        storage_path: Optional[str] = None,
    ) -> None:
        self._master_key = _coerce_master(master_key)
        self._secrets: Dict[str, str] = {}
        self._meta: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._storage_path: Optional[Path] = (
            Path(storage_path) if storage_path else None
        )
        self._load()

    @property
    def storage_path(self) -> Optional[Path]:
        return self._storage_path

    @property
    def master_key(self) -> str:
        return self._master_key

    def _load(self) -> None:
        if self._storage_path is None or not self._storage_path.exists():
            return
        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._secrets = {}
            return
        except Exception as exc:
            logger.warning("Failed to load secrets from %s: %s", self._storage_path, exc)
            self._secrets = {}
            return
        if not isinstance(data, dict):
            self._secrets = {}
            return
        secrets_payload: Dict[str, str] = {}
        meta_payload: Dict[str, Dict[str, Any]] = {}
        for k, v in data.items():
            if not isinstance(k, str):
                continue
            if isinstance(v, str):
                secrets_payload[k] = v
            elif isinstance(v, dict):
                encrypted = v.get("value")
                if isinstance(encrypted, str):
                    secrets_payload[k] = encrypted
                    meta = {mk: mv for mk, mv in v.items() if mk != "value"}
                    if meta:
                        meta_payload[k] = meta
        self._secrets = secrets_payload
        self._meta = meta_payload

    def _save(self) -> None:
        if self._storage_path is None:
            return
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            data: Dict[str, Any] = {}
            for k, v in self._secrets.items():
                meta = self._meta.get(k)
                if meta:
                    entry: Dict[str, Any] = dict(meta)
                    entry["value"] = v
                    data[k] = entry
                else:
                    data[k] = v
            self._storage_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save secrets to %s: %s", self._storage_path, exc)

    def set(self, key: str, value: str) -> None:
        if not isinstance(key, str) or not key:
            raise ValueError("key must be a non-empty string")
        if value is None or not isinstance(value, str):
            raise ValueError("value must be a string")
        with self._lock:
            self._secrets[key] = encrypt_api_key(value, master_key=self._master_key)
            self._meta[key] = {
                "updated_at": _now_iso(),
                "id": _new_id("sec_"),
            }
            self._save()

    def get(self, key: str) -> Optional[str]:
        if not isinstance(key, str):
            return None
        with self._lock:
            enc = self._secrets.get(key)
            if enc is None:
                return None
            try:
                return decrypt_api_key(enc, master_key=self._master_key)
            except Exception:
                return None

    def delete(self, key: str) -> bool:
        if not isinstance(key, str):
            return False
        with self._lock:
            existed = self._secrets.pop(key, None) is not None
            self._meta.pop(key, None)
            if existed:
                self._save()
            return existed

    def list_keys(self) -> List[str]:
        with self._lock:
            return list(self._secrets.keys())

    def has(self, key: str) -> bool:
        if not isinstance(key, str):
            return False
        with self._lock:
            return key in self._secrets

    def count(self) -> int:
        with self._lock:
            return len(self._secrets)

    def clear(self) -> int:
        with self._lock:
            n = len(self._secrets)
            self._secrets.clear()
            self._meta.clear()
            self._save()
            return n

    def to_dict(self) -> Dict[str, Optional[str]]:
        with self._lock:
            out: Dict[str, Optional[str]] = {}
            for k, v in self._secrets.items():
                try:
                    out[k] = decrypt_api_key(v, master_key=self._master_key)
                except Exception:
                    out[k] = None
            return out

    def get_metadata(self, key: str) -> Optional[Dict[str, Any]]:
        if not isinstance(key, str):
            return None
        with self._lock:
            meta = self._meta.get(key)
            return dict(meta) if meta else None

    def update_metadata(self, key: str, **fields: Any) -> bool:
        if not isinstance(key, str) or not key:
            return False
        with self._lock:
            if key not in self._secrets:
                return False
            self._meta.setdefault(key, {"updated_at": _now_iso()})
            self._meta[key].update(fields)
            self._meta[key]["updated_at"] = _now_iso()
            self._save()
            return True

    def rotate_secret(self, key: str, new_value: str) -> bool:
        if not isinstance(key, str) or not key:
            return False
        if not isinstance(new_value, str) or not new_value:
            raise ValueError("new_value must be a non-empty string")
        with self._lock:
            if key not in self._secrets:
                return False
            self._secrets[key] = encrypt_api_key(new_value, master_key=self._master_key)
            self._meta.setdefault(key, {"updated_at": _now_iso()})
            self._meta[key]["rotated_at"] = _now_iso()
            self._meta[key]["updated_at"] = _now_iso()
            self._save()
            return True


_singleton: Optional[SecretStore] = None
_singleton_lock = threading.Lock()


def get_secret_store() -> SecretStore:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            mk = os.environ.get("NEUROVA_MASTER_KEY", "")
            path = os.environ.get("NEUROVA_SECRETS_PATH", _DEFAULT_PATH)
            try:
                _singleton = SecretStore(master_key=mk, storage_path=path)
            except Exception as exc:
                logger.warning("Failed to initialize singleton SecretStore: %s", exc)
                _singleton = SecretStore(master_key=mk, storage_path=None)
    return _singleton


def _reset_singleton_for_tests() -> None:
    global _singleton
    with _singleton_lock:
        _singleton = None
