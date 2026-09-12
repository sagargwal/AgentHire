from datetime import datetime, timedelta
from jose import jwt, JWTError
from passlib.context import CryptContext
import os
import secrets
import hashlib

# ─── Constants ────────────────────────────────────────────────────────────────

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15   # short-lived — refresh token handles long sessions
REFRESH_TOKEN_EXPIRE_DAYS = 7       # long-lived — stored in DB, can be revoked

# bcrypt hashing context — used for passwords
# deprecated="auto" handles future algorithm migrations gracefully
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ─── Secret Key ───────────────────────────────────────────────────────────────

def get_secret_key() -> str:
    """
    Read JWT secret from environment.
    Crashes at startup if missing — intentional, misconfiguration must be visible.
    """
    secret = os.getenv("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY not set in environment")
    return secret


# ─── Password Hashing ─────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """
    One-way bcrypt hash of a plain password.
    bcrypt auto-generates a unique salt per call — embedded in the returned string.
    The original password is never stored anywhere.
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against a stored bcrypt hash.
    bcrypt extracts the embedded salt from hashed_password, re-hashes
    plain_password with it, and compares — never reverses the hash.
    """
    return pwd_context.verify(plain_password, hashed_password)


# ─── Access Token (JWT) ───────────────────────────────────────────────────────

def create_access_token(data: dict) -> str:
    """
    Create a signed JWT. data should be {"sub": user_email}.
    Token expires in ACCESS_TOKEN_EXPIRE_MINUTES (15 min).
    Anyone can read the payload — it is signed, not encrypted.
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, get_secret_key(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """
    Verify JWT signature and expiry. Returns payload dict if valid.
    Raises ValueError on any failure — expired, tampered, malformed.
    ValueError used (not JWTError) so callers don't need to import jose.
    """
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise ValueError("Invalid or expired token")


# ─── Refresh Token ────────────────────────────────────────────────────────────

def create_refresh_token() -> str:
    """
    Generate a cryptographically random refresh token.
    Returns the RAW token — this goes into the httpOnly cookie.
    Never store this raw value in the DB — hash it first.
    32 bytes = 256 bits of randomness — brute force is computationally impossible.
    """
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """
    SHA-256 hash of the raw refresh token — this is what gets stored in the DB.
    SHA-256 (not bcrypt) because the token is already random — no need for salting.
    Fast is fine here: 32-byte random tokens cannot be brute-forced regardless of speed.
    Verification: hash the incoming cookie value, compare against DB — same principle as passwords.
    """
    return hashlib.sha256(token.encode()).hexdigest()