"""Optional LLM wording pass. The language model only rewrites wording; it never sees or
writes numbers. Numbers are placeholders ({{N1}}, ...) and citations/row IDs are placeholders
({{R1}}, ...), all filled in by code afterwards.

Guard: the rewrite is rejected (and the deterministic template text used instead) unless it
keeps exactly the same placeholders and contains no digits of its own.

Enabled only when BIJLICAST_LLM=anthropic and Anthropic credentials are available.
Model: Claude Opus 5.5 with server-side refusal fallbacks enabled.
"""

from __future__ import annotations

import os
import re

PLACEHOLDER = re.compile(r"\{\{[NR]\d+\}\}")
DIGITS = re.compile(r"[0-9٠-٩۰-۹]")

SYSTEM = (
    "You edit short answers for electricity planners in Pakistan. Rewrite the draft so it reads "
    "clearly and naturally in the requested language, keeping every fact. Placeholders like "
    "{{N1}} stand for numbers and {{R1}} for citations: keep each one exactly once, unchanged, "
    "next to the claim it supports, and never write any digits yourself. Do not add claims, "
    "advice or numbers that are not in the draft. Return only the rewritten answer."
)


def enabled() -> bool:
    return os.environ.get("BIJLICAST_LLM", "").lower() == "anthropic"


def polish(draft_with_placeholders: str, lang: str) -> tuple[str, bool]:
    """Return (text_with_placeholders, used_llm). Falls back to the draft on any problem."""
    if not enabled():
        return draft_with_placeholders, False
    try:
        import anthropic

        client = anthropic.Anthropic()
        resp = client.beta.messages.create(
            model="claude-opus-5-5",
            max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low"},
            system=SYSTEM,
            messages=[{"role": "user", "content":
                       f"Language: {'Urdu' if lang == 'ur' else 'English'}\n\nDraft:\n{draft_with_placeholders}"}],
        )
        if resp.stop_reason in ("refusal", "max_tokens"):
            return draft_with_placeholders, False
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
    except Exception:
        return draft_with_placeholders, False
    same = sorted(PLACEHOLDER.findall(text)) == sorted(PLACEHOLDER.findall(draft_with_placeholders))
    if not text or not same or DIGITS.search(PLACEHOLDER.sub("", text)):
        return draft_with_placeholders, False
    return text, True
