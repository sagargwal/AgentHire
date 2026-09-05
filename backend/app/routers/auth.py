from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Response, Cookie
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    hash_refresh_token
)
from app.models.user import User
from app.models.refresh_token import RefreshToken

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_TOKEN_EXPIRE_DAYS = 7


# ─── Request Schemas ──────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ─── Helper ───────────────────────────────────────────────────────────────────

def issue_tokens(user: User, db: Session, response: Response) -> TokenResponse:
    """
    Create access + refresh tokens for a user.
    Access token returned in response body.
    Refresh token stored in DB (hashed) and set as httpOnly cookie.
    Reused by both signup and login to avoid duplication.
    """
    # create access token — short lived, stateless JWT
    access_token = create_access_token({"sub": user.email})

    # create refresh token — long lived, stored in DB
    raw_refresh_token = create_refresh_token()
    hashed = hash_refresh_token(raw_refresh_token)
    expires_at = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    # store hashed refresh token in MySQL
    db_token = RefreshToken(
        user_id=user.id,
        token_hash=hashed,
        expires_at=expires_at,
        revoked=False
    )
    db.add(db_token)
    db.commit()

    # set raw refresh token as httpOnly cookie
    # httpOnly=True — JavaScript cannot read this cookie (XSS protection)
    # secure=True — only sent over HTTPS (set False for local dev)
    # samesite="lax" — cookie sent on same-site requests and top-level navigations
    response.set_cookie(
        key="refresh_token",
        value=raw_refresh_token,
        httponly=True,
        secure=False,       # change to True in production (HTTPS)
        samesite="lax",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60  # seconds
    )

    return TokenResponse(access_token=access_token)


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/signup", response_model=TokenResponse)
def signup(
    payload: SignupRequest,
    response: Response,
    db: Session = Depends(get_db)
):
    # check if email already registered
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # create user with hashed password
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        name=payload.name
    )
    db.add(user)
    db.flush()  # get user.id before issuing tokens

    return issue_tokens(user, db, response)


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db)
):
    # find user by email
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    # verify password against stored hash
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    return issue_tokens(user, db, response)


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    response: Response,
    db: Session = Depends(get_db),
    refresh_token: Optional[str] = Cookie(None)  # reads httpOnly cookie
):
    # no cookie sent
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No refresh token provided"
        )

    # hash incoming token and look it up in DB
    hashed = hash_refresh_token(refresh_token)
    db_token = db.query(RefreshToken).filter(
        RefreshToken.token_hash == hashed,
        RefreshToken.revoked == False,
        RefreshToken.expires_at > datetime.utcnow()
    ).first()

    if not db_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )

    # get the user this token belongs to
    user = db.query(User).filter(User.id == db_token.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    # rotate — revoke old token before issuing new one
    # if attacker steals old token and tries to use it after rotation,
    # it will be rejected because revoked=True
    db_token.revoked = True
    db.commit()

    return issue_tokens(user, db, response)


@router.post("/logout")
def logout(
    response: Response,
    db: Session = Depends(get_db),
    refresh_token: Optional[str] = Cookie(None)
):
    # if cookie exists, revoke the token in DB
    if refresh_token:
        hashed = hash_refresh_token(refresh_token)
        db_token = db.query(RefreshToken).filter(
            RefreshToken.token_hash == hashed
        ).first()
        if db_token:
            db_token.revoked = True
            db.commit()

    # clear the cookie regardless — even if token wasn't found
    response.delete_cookie(key="refresh_token")
    return {"message": "Logged out successfully"}