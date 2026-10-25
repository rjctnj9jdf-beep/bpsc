"Пароли, токены, шифрование"
import base64
import hashlib
import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SECRET = os.getenv("BPSC_SECRET", "dev-secret-change-me-in-production-32b!")
_KEY = hashlib.sha256(os.getenv("BPSC_KEY", "dev-key-change-me").encode()).digest()  # 256 бит


def hash_password(password: str) -> str:
    rounds = int(os.getenv("BPSC_BCRYPT_ROUNDS", "12"))
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def make_token(user_id: int, role: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    return jwt.encode({"sub": str(user_id), "role": role, "exp": exp}, SECRET, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET, algorithms=["HS256"])


def encrypt(text: str) -> str:
    nonce = os.urandom(12)
    return base64.b64encode(nonce + AESGCM(_KEY).encrypt(nonce, text.encode(), None)).decode()


def decrypt(token: str) -> str:
    raw = base64.b64decode(token)
    return AESGCM(_KEY).decrypt(raw[:12], raw[12:], None).decode()
