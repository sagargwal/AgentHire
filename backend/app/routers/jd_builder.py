from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from langgraph.types import Command
import uuid
from app.agents.jd_builder.graph import chat_bot
from app.core.auth_dependency import verify_token
from app.core.database import engine
from app.models.user import User
from app.models.refresh_token import RefreshToken
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

router = APIRouter(prefix="/jd-builder", tags=["jd-builder"])

# creates a session factory for MySQL queries
# same pattern used throughout the project
DBSession = sessionmaker(bind=engine)


class StartSessionRequest(BaseModel):
    initial_message: str


class MessageRequest(BaseModel):
    message: str


def get_user_from_email(email: str):
    """
    Fetch the full User object from MySQL using email.
    verify_token only returns the email string — we need
    the full user to check role and token limits.
    """
    db = DBSession()
    try:
        # query users table for this email
        user = db.query(User).filter(User.email == email).first()
        return user
    finally:
        db.close()


def check_token_limit(user: User):
    """
    Check if this user has exceeded their token limit.
    Admin accounts (token_limit=NULL) are always allowed.
    Raises HTTP 429 if limit is exceeded.
    """
    # admin has NULL token_limit = unlimited
    # if token_limit is None, skip the check entirely
    if user.token_limit is None:
        return  # admin — no limit, proceed

    # check if tokens used has reached or exceeded the limit
    if user.tokens_used >= user.token_limit:
        # HTTP 429 = Too Many Requests — standard code for rate limiting
        raise HTTPException(
            status_code=429,
            detail=(
                f"You have reached your token limit of {user.token_limit}. "
                f"Contact the administrator to request additional access."
            )
        )


def add_tokens_used(email: str, tokens: int):
    """
    Increment the tokens_used counter for this user in MySQL.
    Called after every successful agent turn.

    email: the user's email (used to find them in DB)
    tokens: how many tokens were used in this turn
    """
    db = DBSession()
    try:
        # UPDATE users SET tokens_used = tokens_used + :tokens
        # WHERE email = :email
        # This adds the new tokens to whatever was already used
        db.execute(
            text("UPDATE users SET tokens_used = tokens_used + :tokens WHERE email = :email"),
            {"tokens": tokens, "email": email}
        )
        db.commit()
    except Exception as e:
        # if update fails, log it but don't crash the request
        # the JD was already generated — don't punish the user
        print(f"Warning: failed to update tokens_used for {email}: {e}")
    finally:
        db.close()


def get_exact_tokens(result: dict) -> int:
    """
    Extract exact token count from OpenAI API response metadata.
    LangGraph stores token usage in each AIMessage's response_metadata.
    We sum across all AI messages in this turn since the agent
    may make multiple LLM calls (one per reasoning step).
    """
    total_tokens = 0
    messages = result.get("messages", [])

    for msg in messages:
        # only AIMessage objects have response_metadata
        # HumanMessage and ToolMessage do not
        if hasattr(msg, "response_metadata"):
            usage = msg.response_metadata.get("token_usage", {})
            if usage:
                # total_tokens = prompt_tokens + completion_tokens
                # this is the exact count OpenAI charged us for
                total_tokens += usage.get("total_tokens", 0)

    # if no usage found (shouldn't happen but defensive)
    # fall back to 0 rather than crashing
    return total_tokens if total_tokens > 0 else 0


@router.post("/sessions")
def start_session(payload: StartSessionRequest, user_email: str = Depends(verify_token)):
    # get full user object from MySQL
    user = get_user_from_email(user_email)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # check token limit BEFORE running the agent
    # if limit exceeded → 429 error, agent never runs
    check_token_limit(user)

    session_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": session_id}}

    result = chat_bot.invoke(
        {"messages": [HumanMessage(content=payload.initial_message)], "jd_draft": {}, "status": "drafting"},
        config=config
    )

    # estimate tokens used in this turn
    tokens_used = get_exact_tokens(result)

    # update the user's token counter in MySQL
    add_tokens_used(user_email, tokens_used)

    return _format_response(session_id, result)


@router.post("/sessions/{session_id}/message")
def send_message(session_id: str, payload: MessageRequest, user_email: str = Depends(verify_token)):
    # get full user object from MySQL
    user = get_user_from_email(user_email)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # check token limit BEFORE running the agent
    check_token_limit(user)

    config = {"configurable": {"thread_id": session_id}}

    state = chat_bot.get_state(config)
    is_paused = bool(state.next)

    if is_paused:
        result = chat_bot.invoke(Command(resume=payload.message), config=config)
    else:
        result = chat_bot.invoke(
            {"messages": [HumanMessage(content=payload.message)]},
            config=config
        )

    # estimate and record tokens used
    tokens_used = get_exact_tokens(result)
    add_tokens_used(user_email, tokens_used)

    return _format_response(session_id, result)


def _format_response(session_id: str, result: dict):
    if "__interrupt__" in result:
        interrupt_obj = result["__interrupt__"][0]
        return {"session_id": session_id, "reply": interrupt_obj.value, "paused": True}

    last_message = result["messages"][-1]
    return {"session_id": session_id, "reply": last_message.content, "paused": False}

def add_tokens_used(email: str, tokens: int):
    """
    Increment tokens_used for this user.
    Sends email notification when user crosses 80% of their limit.
    """
    db = DBSession()
    try:
        # get current usage before update
        user = db.query(User).filter(User.email == email).first()
        if not user:
            return

        old_used = user.tokens_used
        new_used = old_used + tokens

        # update the counter
        db.execute(
            text("UPDATE users SET tokens_used = tokens_used + :tokens WHERE email = :email"),
            {"tokens": tokens, "email": email}
        )
        db.commit()

        # send notification if user just crossed 80% threshold
        # check old_used < threshold AND new_used >= threshold
        # this ensures we notify exactly once, not on every request after 80%
        if user.token_limit:
            threshold = int(user.token_limit * 0.8)
            if old_used < threshold and new_used >= threshold:
                send_limit_notification(email, new_used, user.token_limit)

    except Exception as e:
        print(f"Warning: failed to update tokens_used for {email}: {e}")
    finally:
        db.close()


def send_limit_notification(user_email: str, tokens_used: int, token_limit: int):
    """
    Send email to admin when a user crosses 80% of their token limit.
    Uses Gmail SMTP — add GMAIL_APP_PASSWORD to your .env file.
    """
    import smtplib
    from email.mime.text import MIMEText
    import os

    # your Gmail and app password from .env
    gmail_user = os.getenv("NOTIFICATION_EMAIL")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD")

    if not gmail_user or not gmail_password:
        # if email not configured, just log it
        print(f"NOTIFICATION: {user_email} has used {tokens_used}/{token_limit} tokens (80% threshold crossed)")
        return

    try:
        msg = MIMEText(
            f"User {user_email} has used {tokens_used} of {token_limit} tokens "
            f"({int(tokens_used/token_limit*100)}%).\n\n"
            f"Reset their limit:\n"
            f"UPDATE users SET tokens_used=0 WHERE email='{user_email}';"
        )
        msg['Subject'] = f"AgentHire: {user_email} at 80% token limit"
        msg['From'] = gmail_user
        msg['To'] = gmail_user  # notify yourself

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(gmail_user, gmail_password)
            server.send_message(msg)

        print(f"Notification sent for {user_email}")

    except Exception as e:
        # email failed — just log, don't crash
        print(f"Warning: notification email failed: {e}")