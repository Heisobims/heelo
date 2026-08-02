from __future__ import annotations

from pydantic import BaseModel, Field


class SubmitFeedbackRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: str | None = Field(None, max_length=2000)
