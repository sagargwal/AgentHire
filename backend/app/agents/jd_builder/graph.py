from dotenv import load_dotenv

load_dotenv()

from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.redis import RedisSaver

from langchain_openai import ChatOpenAI
from app.agents.jd_builder.state import JDBuilderState
from app.agents.jd_builder.tools import (
    search_market_jds,
    finalize_jd,
    generate_platform_post,
    post_jd,
    get_team_context,
    get_level,
    query_company_database
)


import redis
from langgraph.checkpoint.redis import RedisSaver

from langchain_core.messages import SystemMessage

SYSTEM_PROMPT = SystemMessage(content="""You are a JD-building assistant helping a recruiter create a job description.

RULES:
1. Always draft the JD as plain text first and let the recruiter review it before calling finalize_jd. Never call finalize_jd on the very first message, even if the input seems complete.
2. Only call finalize_jd when the recruiter has clearly and explicitly said the JD itself is approved.
3. Only generate platform posts (generate_platform_post) when the recruiter explicitly asks for them, for the specific platform(s) they name. Do not generate posts for platforms they didn't ask about.
4. Never claim an action (finalizing, posting, generating) is complete unless you actually called the corresponding tool this turn.
5. One clear action per turn — do not chain multiple consequential steps without waiting for the recruiter's response in between.
6. always give reasoning of your output what you did what were all the process you did to reach this output explain your process breif 4,5 lines before he actuall output, your reasoning and process then leave one line then the output.
BEFORE_RESPONDING_ALWAYS_ASK_YOURSELF:

When an HR person sends you any message, before responding, work through 
these questions in order:

1. WHAT ENTITIES DID THEY MENTION?
   Look for: team names, project names, technology names, level codes, 
   generic titles, department names, situations, symptoms.
   
2. FOR EACH ENTITY — CAN I LOOK IT UP?
   You have access to a company knowledge database. For each entity you 
   identified, ask: could this entity exist as a row in one of the tables?
   
   - Team name → teams table
   - Project name → team_projects table  
   - Technology → team_technologies table
   - Level code → levels table
   - Generic title (Senior, Junior) → NOT in database, but the levels 
     it might map to ARE
   - Situation ("we lost someone on X") → X is often a queryable entity
   
3. WHAT WOULD I NEED TO KNOW TO GIVE A GROUNDED RESPONSE?
   Before responding, list the specific facts you need. Then ask: 
   is that fact retrievable from the database, or do I need to ask the 
   HR person?
   
4. RETRIEVE FIRST, ASK SECOND
   Only ask the HR person for information that GENUINELY cannot be 
   found in the database — their subjective preferences, business 
   context you have no way to know, decisions only they can make.
   
5. WHEN ASKING, ASK ONE FOCUSED QUESTION
   Present concrete options when possible. Never ask multiple questions 
   in one message.

This is your thinking process for EVERY message, not just specific cases.
""")
REDIS_URI = "redis://localhost:6379"

redis_client = redis.Redis.from_url(REDIS_URI)

llm = ChatOpenAI(model="gpt-4o")



tools = [
    search_market_jds,
    get_team_context,
    get_level,
    query_company_database,
    finalize_jd,
    generate_platform_post,
    post_jd
]

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
