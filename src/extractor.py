import json
import logging
import os

import litellm
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")


async def categorize_content(markdown_text: str) -> list[str]:
    """Use LLM to auto-categorize page content into relevant categories.

    Returns a list of category labels like ["courses", "fees", "scholarships"].
    """
    # Truncate to avoid token limits — first 3000 chars is usually enough
    truncated = markdown_text[:3000]

    prompt = f"""Analyze this webpage content from an educational institution.
What categories of information does it contain?

Return ONLY a JSON array of concise category labels (lowercase, 1-2 words each).
Common categories include but are NOT limited to: courses, fees, scholarships,
admissions, placements, events, faculty, rankings, partnerships, campus, research,
alumni, internships, student life.

Only include categories that are clearly present in the content.

Content:
{truncated}

JSON array:"""

    try:
        response = await litellm.acompletion(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.1,
        )
        text = response.choices[0].message.content.strip()
        # Parse the JSON array from response
        # Handle cases where LLM wraps in markdown code block
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        categories = json.loads(text)
        if isinstance(categories, list):
            return [str(c).lower().strip() for c in categories]
    except Exception as e:
        logger.warning(f"LLM categorization failed: {e}")

    return ["uncategorized"]


async def is_page_relevant(url: str, markdown_text: str) -> bool:
    """Use LLM to decide if a discovered page is educationally relevant.

    Filters out privacy policies, cookie notices, generic corporate pages, etc.
    """
    truncated = markdown_text[:2000]

    prompt = f"""You are filtering pages from an educational institution's website.
Is this page relevant for competitive intelligence? Relevant pages contain info about:
courses, programs, fees, scholarships, admissions, placements, rankings, faculty,
events, partnerships, research, student outcomes, campus facilities.

Irrelevant pages: privacy policy, terms of service, cookie notices, login pages,
generic navigation, job postings for staff, IT help desk, etc.

URL: {url}
Content preview:
{truncated}

Answer with ONLY "yes" or "no":"""

    try:
        response = await litellm.acompletion(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=5,
            temperature=0.0,
        )
        answer = response.choices[0].message.content.strip().lower()
        return answer.startswith("yes")
    except Exception as e:
        logger.warning(f"LLM relevance check failed for {url}: {e}")
        return True  # Default to relevant if LLM fails


async def summarize_changes(diff_text: str, url: str) -> str:
    """Use LLM to produce a human-readable summary of what changed on a page."""
    truncated_diff = diff_text[:4000]

    prompt = f"""Summarize the following changes detected on an educational institution's webpage.
Be concise (1-3 sentences). Focus on what's practically important: new courses, fee changes,
scholarship updates, admission deadlines, placement stats, etc.

URL: {url}

Changes (unified diff):
{truncated_diff}

Summary:"""

    try:
        response = await litellm.acompletion(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.2,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"LLM summarization failed: {e}")
        return "Content changed (LLM summary unavailable)"
