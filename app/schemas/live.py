from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


class PollCreateRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    options: list[str] = Field(..., min_length=2, max_length=10)


class PollOptionOut(BaseModel):
    id: uuid.UUID
    text: str
    vote_count: int


class PollOut(BaseModel):
    id: uuid.UUID
    question: str
    status: Literal["draft", "open", "closed"]
    options: list[PollOptionOut]
    created_at: str


class PollVoteRequest(BaseModel):
    option_id: uuid.UUID


class QuestionCreateRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=500)
    author_name: str | None = Field(None, max_length=100)


class QuestionOut(BaseModel):
    id: uuid.UUID
    body: str
    author_name: str | None
    upvotes: int
    is_answered: bool
    created_at: str


class QuestionUpdateRequest(BaseModel):
    is_answered: bool | None = None
    is_hidden: bool | None = None
