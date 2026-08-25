from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages


class JDBuilderState(TypedDict):
    messages: Annotated[list, add_messages]
    jd_draft: dict
    status: str