"""LLM narration for computed warehouse investment reports."""

from __future__ import annotations

import json
from typing import Any

from .presale_parser import ANTHROPIC_MODEL
from .presale_store import json_safe


REPORT_SYSTEM_PROMPT = """
You are a senior structured-credit investment analyst writing a concise credit-committee memo.
You narrate only from the supplied fact packet. Python has already computed the model outputs.

Contract:
- Lead with the investable conclusion and consequence.
- Use every numeric claim only from the fact packet. Do not calculate new figures.
- If evidence is missing, say what is missing and why it matters; do not invent a value.
- Preserve source modality: sourced, assumed, modeled, missing, or inferred.
- Strong negative calls are allowed when the computed facts support them.
- Do not import external market ranges, statutory claims, legal doctrine, rating views, or market-standard terms.
- Do not recommend generic remedy bundles. Recommend one primary action tied to the model result.
- If levered equity IRR is below 0%, explicitly state that an equity investor would not want to fund the structure.
- Keep it professional, direct, and concise. Avoid generic AI phrases, drama, and filler.

Output:
- Markdown only.
- Use exactly these sections:
  1. Recommendation
  2. Facility
  3. Return Profile
  4. Protection
  5. Optimal Structure
  6. Stress Summary
  7. Key Risks
  8. Conclusion
- Keep the memo under 650 words.
"""

FORBIDDEN_UNSUPPORTED_PHRASES = (
    "market-standard",
    "market standard",
    "uncapped",
    "unlimited indemnity",
    "automatic price cut",
    "deal-breaker",
)


def write_llm_investment_report(fact_packet: dict[str, Any], api_key: str) -> str:
    try:
        from anthropic import Anthropic
    except ImportError as exc:  # pragma: no cover - dependency check is UI-facing.
        raise RuntimeError("anthropic is not installed. Run `pip install -r requirements.txt`.") from exc

    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=2200,
        temperature=0.2,
        system=REPORT_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                "Write the investment report from this fact packet. "
                "Do not add facts outside this JSON.\n\n"
                + json.dumps(json_safe(fact_packet), sort_keys=True)
            ),
        }],
    )
    text = "".join(
        getattr(block, "text", "")
        for block in response.content
        if getattr(block, "type", None) == "text"
    ).strip()
    validate_llm_report(text, fact_packet)
    return text


def validate_llm_report(report: str, fact_packet: dict[str, Any]) -> None:
    if not report:
        raise RuntimeError("LLM report was empty.")
    lowered = report.lower()
    for phrase in FORBIDDEN_UNSUPPORTED_PHRASES:
        if phrase in lowered:
            raise RuntimeError(f"LLM report used unsupported remedy/market phrase: {phrase}")

    recommendation = str(fact_packet.get("recommendation", {}).get("action", "")).lower()
    normalized_report = lowered.replace("-", " ")
    normalized_recommendation = recommendation.replace("-", " ")
    if recommendation and recommendation not in lowered and normalized_recommendation not in normalized_report:
        raise RuntimeError("LLM report omitted the computed recommendation action.")

    advance = fact_packet.get("recommendation", {}).get("recommended_advance_pct")
    if advance is not None and f"{float(advance):.0f}%" not in report:
        raise RuntimeError("LLM report omitted the recommended advance rate.")

    equity_irr = fact_packet.get("recommendation", {}).get("levered_equity_irr")
    if equity_irr is not None and float(equity_irr) < 0 and "equity investor" not in lowered:
        raise RuntimeError("LLM report omitted the required negative-equity-IRR investor warning.")
