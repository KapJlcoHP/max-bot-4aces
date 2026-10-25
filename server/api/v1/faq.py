"""Публичный справочник часто задаваемых вопросов."""

import json
from pathlib import Path

from fastapi import APIRouter

from core.schemas import FaqOut

router = APIRouter()
FAQ_PATH = Path(__file__).resolve().parents[3] / "content" / "faq.json"


def load_faq() -> FaqOut:
    """Read the versioned FAQ content without touching the application database."""
    with FAQ_PATH.open(encoding="utf-8") as source:
        payload = json.load(source)
    return FaqOut.model_validate(payload)


@router.get("/faq", response_model=FaqOut)
def faq() -> FaqOut:
    return load_faq()
