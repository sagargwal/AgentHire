from elasticsearch import Elasticsearch
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.types import interrupt

es_client = Elasticsearch("http://localhost:9200")
post_llm = ChatOpenAI(model="gpt-4o-mini")
interpreter_llm = ChatOpenAI(model="gpt-4o-mini")


def _extract_title(jd_draft: dict) -> str:
    return jd_draft.get("title") or jd_draft.get("job_title", "Untitled role")


def _extract_skills(jd_draft: dict) -> list:
    return jd_draft.get("skills") or jd_draft.get("required_skills", [])


def _extract_description(jd_draft: dict) -> str:
    return jd_draft.get("description") or jd_draft.get("job_description", "")


@tool
def search_market_jds(query: str, seniority: str = None) -> str:
    """Search for similar job descriptions in the market JD database.
    Use this when the recruiter's input is vague and you need real examples
    of how similar roles are typically described, including common skills
    and phrasing. Pass a short search phrase like 'backend engineer' or
    'senior data analyst'. Optionally pass seniority ('junior', 'mid', or
    'senior') if the recruiter specified a level, to narrow results."""
    try:
        if seniority:
            query_body = {
                "bool": {
                    "must": {"match": {"description": query}},
                    "filter": {"term": {"seniority": seniority}}
                }
            }
        else:
            query_body = {"match": {"description": query}}

        response = es_client.search(
            index="jds",
            query=query_body,
            size=3
        )

        hits = response["hits"]["hits"]
        if not hits:
            return "No similar job descriptions found."

        results = []
        for hit in hits:
            source = hit["_source"]
            results.append(f"Title: {source['title']}\n{source['description'][:200]}...")

        return "\n\n".join(results)
    except Exception as e:
        print(f"search_market_jds error: {e}")
        return f"Search failed: {str(e)}. Proceed without market examples."


@tool
def finalize_jd(jd_draft: dict) -> str:
    """Call this when you believe the JD is ready to finalize. This will
    pause and ask the recruiter for confirmation in their own words before
    actually locking the draft. Pass the full jd_draft dict with keys:
    title, description, skills."""
    title = _extract_title(jd_draft)

    human_response = interrupt(
        f"Ready to finalize '{title}'. Reply with your decision — approve, "
        f"request changes, or reject — in your own words."
    )

    interpretation_prompt = f"""A recruiter was asked to approve finalizing a job description.
They replied: "{human_response}"

Classify their intent as exactly one of: APPROVED, REJECTED, or CHANGES_REQUESTED.
If CHANGES_REQUESTED, summarize the requested changes in one short sentence.

Respond in exactly this format:
INTENT: <APPROVED|REJECTED|CHANGES_REQUESTED>
DETAILS: <summary if changes requested, else "none">"""

    interpretation = interpreter_llm.invoke(interpretation_prompt).content

    if "INTENT: APPROVED" in interpretation:
        return f"JD finalized: {title}"
    elif "INTENT: REJECTED" in interpretation:
        return f"Recruiter declined to finalize '{title}'. Draft remains open for editing."
    else:
        return f"Recruiter requested changes before finalizing: {interpretation}"


@tool
def generate_platform_post(jd_draft: dict, platform: str) -> str:
    """Generate compelling, platform-appropriate post copy from a finalized
    JD, using an LLM to write real marketing language rather than a plain
    template. platform should be 'linkedin' or 'naukri'. Pass the full
    jd_draft dict with keys: title, description, skills."""
    title = _extract_title(jd_draft)
    description = _extract_description(jd_draft)
    skills = ", ".join(_extract_skills(jd_draft))

    prompt = f"""Write a short, engaging {platform} post to advertise this job opening.
Make it sound exciting but professional, use relevant emojis sparingly, and end with a call to action.

Title: {title}
Description: {description}
Key skills: {skills}"""

    response = post_llm.invoke(prompt)
    return response.content


@tool
def post_jd(jd_draft: dict, platform_post_text: str) -> str:
    """Call this after generate_platform_post has produced text and the JD
    is finalized. Pauses to confirm with the recruiter before simulating
    the publish. Pass the full jd_draft dict with keys: title, description,
    skills."""
    title = _extract_title(jd_draft)

    human_response = interrupt(
        f"Ready to post this to LinkedIn:\n\n{platform_post_text}\n\n"
        f"Reply to approve, ask for edits, or decline."
    )

    interpretation_prompt = f"""A recruiter was asked to approve publishing a LinkedIn post.
They replied: "{human_response}"

Classify their intent as exactly one of: APPROVED, REJECTED, or CHANGES_REQUESTED.
If CHANGES_REQUESTED, summarize the requested changes in one short sentence.

Respond in exactly this format:
INTENT: <APPROVED|REJECTED|CHANGES_REQUESTED>
DETAILS: <summary if changes requested, else "none">"""

    interpretation = interpreter_llm.invoke(interpretation_prompt).content

    if "INTENT: APPROVED" in interpretation:
        # TODO: replace with real LinkedIn Share API call
        return f"[SIMULATED] Posted to LinkedIn: {title}"
    elif "INTENT: REJECTED" in interpretation:
        return f"Recruiter declined to post '{title}'."
    else:
        return f"Recruiter requested changes before posting: {interpretation}"