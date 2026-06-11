"""Dataclass models mirroring the SQLite schema."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Learning:
    id: Optional[int] = None
    title: str = ""
    content: str = ""
    reflection: Optional[str] = None
    subject: Optional[str] = None
    conversation: Optional[str] = None
    notes: Optional[str] = None
    priority: int = 0
    private: bool = False
    created_at: Optional[datetime] = None
    is_active: bool = True
    tags: list[str] = field(default_factory=list)


@dataclass
class Question:
    id: Optional[int] = None
    learning_id: int = 0
    question: str = ""
    answer: str = ""
    card_type: str = "basic"
    cloze_source: Optional[str] = None
    cloze_index: Optional[int] = None

    stability: float = 0.0
    difficulty: float = 0.0
    state: int = 0
    lapses: int = 0
    last_reviewed_at: Optional[datetime] = None
    next_review_at: Optional[datetime] = None

    suspended: bool = False
    created_at: Optional[datetime] = None
