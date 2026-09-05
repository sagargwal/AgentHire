from fastapi import APIRouter, Depends
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from langgraph.types import Command
import uuid
from app.agents.jd_builder.graph import chat_bot
from app.core.auth_dependency import verify_token

router = APIRouter(prefix="/jd-builder", tags=["jd-builder"])


class StartSessionRequest(BaseModel):
    initial_message: str


class MessageRequest(BaseModel):
    message: str


@router.post("/sessions")
def start_session(payload: StartSessionRequest, user_email: str = Depends(verify_token)):
    session_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": session_id}}

    result = chat_bot.invoke(
        {"messages": [HumanMessage(content=payload.initial_message)], "jd_draft": {}, "status": "drafting"},
        config=config
    )

    return _format_response(session_id, result)


@router.post("/sessions/{session_id}/message")
def send_message(session_id: str, payload: MessageRequest, user_email: str = Depends(verify_token)):
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

    return _format_response(session_id, result)


def _format_response(session_id: str, result: dict):
    if "__interrupt__" in result:
        interrupt_obj = result["__interrupt__"][0]
        return {"session_id": session_id, "reply": interrupt_obj.value, "paused": True}

    last_message = result["messages"][-1]
    return {"session_id": session_id, "reply": last_message.content, "paused": False}