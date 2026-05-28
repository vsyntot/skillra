"""Basic resume skill extraction by keyword matching."""

from __future__ import annotations

import io
import logging
import re

logger = logging.getLogger(__name__)


def extract_skills_from_text(text: str, known_skills: list[str]) -> list[str]:
    """Extract known skills from text using case-insensitive word matching."""

    text_lower = text.lower()
    found: list[str] = []
    for skill in known_skills:
        pattern = r"(?<![\w+.#-])" + re.escape(skill.lower()) + r"(?![\w+.#-])"
        if re.search(pattern, text_lower):
            found.append(skill)
    return found


async def parse_pdf_resume(pdf_bytes: bytes, known_skills: list[str]) -> dict[str, object]:
    """Extract text from a PDF-like payload and return text length plus skills."""

    text = ""
    try:
        import pypdf  # type: ignore[import-untyped]

        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        text = " ".join(page.extract_text() or "" for page in reader.pages)
    except ModuleNotFoundError:
        logger.warning("pypdf not installed; falling back to best-effort text decode")
    except Exception:
        logger.exception("PDF parsing failed; falling back to best-effort text decode")

    if not text:
        text = pdf_bytes.decode("utf-8", errors="ignore")

    skills = extract_skills_from_text(text, known_skills)
    return {"text_length": len(text), "skills": skills}
