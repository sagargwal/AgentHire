import os
from fastapi import APIRouter, Depends, HTTPException, Response, Cookie
from pydantic import BaseModel
from sqlalchemy.orm import sessionmaker
from app.core.database import engine
from app.models.user import User
from app.models.refresh_token import RefreshToken
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token, hash_refresh_token
from app.core.auth_dependency import verify_token
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(prefix="/auth", tags=["auth"])
DBSession = sessionmaker(bind=engine)

# invite code loaded from .env
# set INVITE_CODE=NEXUSHEALTH2026 in your .env file
INVITE_CODE = os.getenv("INVITE_CODE", "NEXUSHEALTH2026")


class SignupRequest(BaseModel):
    email: str
    password: str
    name: str
    company: str = None
    invite_code: str  # required — must match INVITE_CODE to sign up


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/signup")
def signup(payload: SignupRequest, response: Response):
    db = DBSession()
    try:
        # check if email already exists
        existing = db.query(User).filter(User.email == payload.email).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")

        # signup requires a valid invite code
        # note: admin and demo accounts are created manually, never through signup
        if payload.invite_code != INVITE_CODE:
            raise HTTPException(
                status_code=403,
                detail="Signup requires a valid invite code. Contact the administrator."
            )

        role = 'user'
        token_limit = 50000

        user = User(
            email=payload.email,
            hashed_password=hash_password(payload.password),
            name=payload.name,
            company=payload.company,
            role=role,
            tokens_used=0,
            token_limit=token_limit
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        return {
            "message": "Account created successfully",
            "email": user.email,
            "role": user.role
        }

    finally:
        db.close()


@router.post("/login")
def login(payload: LoginRequest, response: Response):
    db = DBSession()
    try:
        # find user by email
        user = db.query(User).filter(User.email == payload.email).first()
        if not user:
            raise HTTPException(status_code=401, detail="Invalid email or password")

        # verify password
        if not verify_password(payload.password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        # create access token — short lived (60 min)
        access_token = create_access_token({"sub": user.email, "role": user.role})

        # create refresh token — long lived (7 days)
        from datetime import datetime, timezone, timedelta
        refresh_token_value = create_refresh_token()
        token_hash = hash_refresh_token(refresh_token_value)
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        # save refresh token to MySQL
        refresh_token = RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at
        )
        db.add(refresh_token)
        db.commit()

        # set refresh token as httpOnly cookie
        # httpOnly = JavaScript cannot read it (XSS protection)
        # secure = only sent over HTTPS
        # samesite = CSRF protection
        response.set_cookie(
            key="refresh_token",
            value=refresh_token_value,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=7 * 24 * 60 * 60  # 7 days in seconds
        )

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "role": user.role
        }

    finally:
        db.close()


@router.post("/refresh")
def refresh(
    response: Response,
    refresh_token: str = Cookie(None)
):
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token")

    db = DBSession()
    try:
        # hash the incoming token to compare against stored hash
        token_hash = hash_refresh_token(refresh_token)

        # find the token in database
        stored_token = db.query(RefreshToken).filter(
            RefreshToken.token_hash == token_hash
        ).first()

        if not stored_token:
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        # check it hasn't expired
        from datetime import datetime, timezone
        if stored_token.expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="Refresh token expired")

        # get the user
        user = db.query(User).filter(User.id == stored_token.user_id).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        # rotate — delete old token, create new one
        db.delete(stored_token)

        from datetime import datetime, timezone, timedelta
        refresh_token_value = create_refresh_token()
        token_hash = hash_refresh_token(refresh_token_value)
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        new_refresh_token = RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at
        )
        db.add(new_refresh_token)
        db.commit()

        # new access token
        access_token = create_access_token({"sub": user.email, "role": user.role})

        response.set_cookie(
            key="refresh_token",
            value=refresh_token_value,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=7 * 24 * 60 * 60
        )

        return {"access_token": access_token, "token_type": "bearer"}

    finally:
        db.close()


@router.post("/logout")
def logout(
    response: Response,
    refresh_token: str = Cookie(None),
    user_email: str = Depends(verify_token)
):
    db = DBSession()
    try:
        if refresh_token:
            # find and delete the refresh token from MySQL
            user = db.query(User).filter(User.email == user_email).first()
            if user:
                token_to_delete = db.query(RefreshToken).filter(
                    RefreshToken.user_id == user.id
                ).first()
                if token_to_delete:
                    db.delete(token_to_delete)
                    db.commit()

        # clear the cookie
        response.delete_cookie("refresh_token")
        return {"message": "Logged out successfully"}

    finally:
        db.close()


@router.get("/me")
def me(user_email: str = Depends(verify_token)):
    db = DBSession()
    try:
        user = db.query(User).filter(User.email == user_email).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return {
            "email": user.email,
            "name": user.name,
            "company": user.company,
            "role": user.role,
            "tokens_used": user.tokens_used,
            "token_limit": user.token_limit
        }
    finally:
        db.close()