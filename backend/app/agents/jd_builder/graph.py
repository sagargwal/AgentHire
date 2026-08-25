from dotenv import load_dotenv

load_dotenv()

from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.redis import RedisSaver

from langchain_openai import ChatOpenAI
from app.agents.jd_builder.state import JDBuilderState
from app.agents.jd_builder.tools import finalize_jd, generate_platform_post, search_market_jds, post_jd


import redis
from langgraph.checkpoint.redis import RedisSaver

from langchain_core.messages import SystemMessage

SYSTEM_PROMPT = SystemMessage(content="""You are a JD-building assistant helping a recruiter create a job description.

RULES:
1. Always draft the JD as plain text first and let the recruiter review it before calling finalize_jd. Never call finalize_jd on the very first message, even if the input seems complete.
2. Only call finalize_jd when the recruiter has clearly and explicitly said the JD itself is approved.
3. Only generate platform posts (generate_platform_post) when the recruiter explicitly asks for them, for the specific platform(s) they name. Do not generate posts for platforms they didn't ask about.
4. Never claim an action (finalizing, posting, generating) is complete unless you actually called the corresponding tool this turn.
5. One clear action per turn — do not chain multiple consequential steps (finalize, then generate, then suggest posting) without waiting for the recruiter's response in between.""")
REDIS_URI = "redis://localhost:6379"

redis_client = redis.Redis.from_url(REDIS_URI)

llm = ChatOpenAI(model="gpt-4o-mini")

tools = [finalize_jd, generate_platform_post, search_market_jds, post_jd]

llm_with_tools = llm.bind_tools(tools)


def chat_node(state: JDBuilderState):
    """LLM node that may answer or request a tool call."""
    messages = [SYSTEM_PROMPT] + state["messages"]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


tool_node = ToolNode(tools)


graph = StateGraph(JDBuilderState)
graph.add_node("chat_node", chat_node)
graph.add_node("tools", tool_node)

graph.add_edge(START, "chat_node")

graph.add_conditional_edges("chat_node", tools_condition)
graph.add_edge("tools", "chat_node")

checkpointer = RedisSaver(redis_client=redis_client)
checkpointer.setup()

chat_bot = graph.compile(checkpointer=checkpointer)
if __name__ == "__main__":
    # ASCII in the terminal — no extra deps
    chat_bot.get_graph().print_ascii()

    # Mermaid syntax you can paste into https://mermaid.live or a markdown file
    print(chat_bot.get_graph().draw_mermaid())

    # Render straight to a PNG file (needs `pip install grandalf` for print_ascii,
    # or for the PNG renderer either pygraphviz or the mermaid.ink web API)
    chat_bot.get_graph().draw_mermaid_png(output_file_path="jd_builder_graph.png")
