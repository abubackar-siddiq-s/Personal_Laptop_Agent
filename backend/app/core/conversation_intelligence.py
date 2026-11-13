from __future__ import annotations
import logging
import re
from typing import Optional, List, Dict, Any
from app.core.db import conn
from app.core.token_budget import estimate_tokens
from app.memory.engine import memory_engine
from app.providers.router import chat_turn

logger = logging.getLogger("laptop_ai.intelligence")

MEMORY_BUDGETS = {
    "groq": 200,
    "gemini": 500,
    "openrouter": 400,
}

def format_memory_block(memories: List[dict]) -> str:
    """Format relevant memories into an isolated, delimited prompt injection block."""
    if not memories:
        return ""
    lines = [
        "[RECALLED PERSISTENT MEMORY - VERIFIED FACTS & PREFERENCES]",
        "Use these remembered facts when relevant. Do not claim you 'just learned' them if they are in memory.",
    ]
    for m in memories:
        cat = m.get("category", "info").replace("_", " ").title()
        key_str = f" · {m['key']}" if m.get("key") else ""
        content = m.get("content", "").strip()
        lines.append(f"- ({cat}{key_str}): {content}")
    lines.append("[END RECALLED MEMORY]\n")
    return "\n".join(lines)


def get_injected_memory_context(user_message: str, provider: str = "groq", model: Optional[str] = None) -> str:
    """
    Retrieve token-budgeted relevant memories for the active user prompt.
    Does NOT inject all memories indiscriminately.
    """
    prov_key = provider.lower().strip() if provider else "groq"
    max_budget = MEMORY_BUDGETS.get(prov_key, 250)
    # Tighter budget for tight-quota models
    if model and ("gpt-oss-20b" in model.lower() or "llama-3-8b" in model.lower()):
        max_budget = min(max_budget, 200)
    relevant = memory_engine.get_relevant_memories(user_message, max_tokens=max_budget, limit=4)
    if not relevant:
        return ""
    return format_memory_block(relevant)


async def generate_conversation_title(first_user_message: str, provider: str = "groq", model: str = "") -> str:
    """Generate a clean 3-6 word title for a conversation."""
    clean_msg = first_user_message.strip()
    if not clean_msg:
        return "New Conversation"

    # Fallback heuristic title
    words = clean_msg.split()
    fallback_title = " ".join(words[:5]).capitalize()
    if len(fallback_title) > 40:
        fallback_title = fallback_title[:37] + "..."

    prompt = (
        f"Generate a concise 3 to 5 word title for a conversation that starts with: \"{clean_msg[:200]}\". "
        "Output ONLY the title with no quotes, formatting, or extra text."
    )
    try:
        res = await chat_turn(
            provider=provider,
            model=model or ("gemini-2.5-flash" if provider == "gemini" else "openai/gpt-oss-20b"),
            messages=[{"role": "user", "content": prompt}],
        )
        title = res.content.strip().strip("'\"").strip()
        if 3 < len(title) <= 50 and "\n" not in title:
            return title
    except Exception as e:
        logger.debug("Automatic title generation LLM turn failed, using fallback: %s", e)

    return fallback_title


async def maybe_summarize_conversation(
    conversation_id: int,
    provider: str = "groq",
    model: str = "",
) -> Optional[dict]:
    """
    Check if conversation has >= 6 messages without a recent summary.
    If so, extract important decisions and project facts and save to memory.
    """
    with conn() as c:
        msgs = c.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()

    if len(msgs) < 6:
        return None

    # Check if we already summarized this conversation recently
    with conn() as c:
        existing_sum = c.execute(
            "SELECT id FROM memories WHERE category = 'conversation_summary' AND conversation_id = ? AND status = 'active' LIMIT 1",
            (conversation_id,),
        ).fetchone()
    if existing_sum and len(msgs) < 14:
        return None

    # Prepare conversation snippet for summarization
    formatted_chat = "\n".join(
        f"{m['role'].upper()}: {m['content'][:300]}" for m in msgs[-10:]
    )

    prompt = (
        "Summarize the key decisions, personal facts, and project outcomes from this conversation in 2-3 concise bullet points. "
        "Do NOT include greetings or small talk. Keep it under 80 words:\n\n" + formatted_chat
    )

    try:
        res = await chat_turn(
            provider=provider,
            model=model or ("gemini-2.5-flash" if provider == "gemini" else "openai/gpt-oss-20b"),
            messages=[{"role": "user", "content": prompt}],
        )
        summary_text = res.content.strip()
        if summary_text and len(summary_text) > 15:
            mem = memory_engine.create(
                category="conversation_summary",
                content=f"Summary of Conversation #{conversation_id}:\n{summary_text}",
                source="conversation_summary",
                key=f"conv_sum_{conversation_id}",
                conversation_id=conversation_id,
                confidence=0.9,
            )
            return mem
    except Exception as e:
        logger.debug("Conversation summarization failed: %s", e)

    return None


async def summarize_conversation(
    conversation_id: int,
    provider: str = "groq",
    model: str = "",
) -> dict:
    """Explicitly summarize conversation and persist as a memory."""
    with conn() as c:
        msgs = c.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()

    if not msgs:
        raise ValueError(f"Conversation #{conversation_id} has no messages to summarize.")

    formatted_chat = "\n".join(
        f"{m['role'].upper()}: {m['content'][:300]}" for m in msgs[-12:]
    )

    prompt = (
        "Summarize the key decisions, personal facts, and project outcomes from this conversation in 2-3 concise bullet points. "
        "Do NOT include greetings or small talk. Keep it under 80 words:\n\n" + formatted_chat
    )

    summary_text = None
    try:
        res = await chat_turn(
            provider=provider,
            model=model or ("gemini-2.5-flash" if provider == "gemini" else "openai/gpt-oss-20b"),
            messages=[{"role": "user", "content": prompt}],
        )
        cand = res.content.strip()
        if cand and len(cand) > 15:
            summary_text = cand
    except Exception as e:
        logger.debug("LLM summarization failed, using heuristic extraction: %s", e)

    if not summary_text:
        user_msgs = [m['content'] for m in msgs if m['role'] == 'user']
        asst_msgs = [m['content'] for m in msgs if m['role'] == 'assistant']
        last_req = user_msgs[-1][:120] if user_msgs else "Discussion"
        last_res = asst_msgs[-1][:150] if asst_msgs else "Concluded"
        summary_text = f"• Focus: {last_req}\n• Outcome: {last_res}"

    mem = memory_engine.create(
        category="conversation_summary",
        content=f"Summary of Conversation #{conversation_id}:\n{summary_text}",
        source="conversation_summary",
        key=f"conv_sum_{conversation_id}",
        conversation_id=conversation_id,
        confidence=0.9,
    )
    return mem


def get_historical_decisions(query: Optional[str] = None, limit: int = 5) -> List[dict]:
    """Retrieve historical project decisions and approved instructions."""
    if query and query.strip():
        candidates = memory_engine.search(query.strip(), category="project_decision", limit=limit)
        inst = memory_engine.search(query.strip(), category="user_approved_instruction", limit=limit)
        combined = {m["id"]: m for m in candidates + inst}
        return list(combined.values())[:limit]

    with conn() as c:
        rows = c.execute(
            """
            SELECT * FROM memories 
            WHERE category IN ('project_decision', 'user_approved_instruction') AND status = 'active'
            ORDER BY updated_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_project_context(project_name: Optional[str] = None, limit: int = 3) -> str:
    """Retrieve active project facts and key project decisions formatted for system prompt context."""
    with conn() as c:
        if project_name:
            p_rows = c.execute(
                "SELECT * FROM memories WHERE category = 'active_project' AND status = 'active' AND (content LIKE ? OR key LIKE ?) LIMIT ?",
                (f"%{project_name}%", f"%{project_name}%", limit),
            ).fetchall()
        else:
            p_rows = c.execute(
                "SELECT * FROM memories WHERE category = 'active_project' AND status = 'active' ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

    if not p_rows:
        return ""

    lines = ["[ACTIVE PROJECT CONTEXT]"]
    for r in p_rows:
        lines.append(f"- {r['content'].strip()}")
    lines.append("[END PROJECT CONTEXT]\n")
    return "\n".join(lines)


def get_conversation_history(conversation_id: int, max_turns: int = 8, max_tokens: int = 1200) -> List[dict]:
    """Retrieve bounded, token-managed conversation history preserving recent turns."""
    from app.core.token_budget import compact_history
    with conn() as c:
        rows = c.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
            (conversation_id, max_turns * 2),
        ).fetchall()
    raw = [dict(r) for r in reversed(rows)]
    return compact_history(raw, max_tokens=max_tokens, max_turns=max_turns)

