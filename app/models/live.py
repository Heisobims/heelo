"""Live audience engagement during an event: polls (organizer-run, live
results) and Q&A (anonymous, free-for-all - no submission approval queue,
organizer can only delete/mark-answered after the fact, per product
decision)."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin


class Poll(Base, TimestampMixin):
    """A single live poll question with multiple choice options."""

    __tablename__ = "polls"
    __table_args__ = (Index("ix_polls_event", "event_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    # draft | open | closed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")

    options: Mapped[list[PollOption]] = relationship(
        "PollOption",
        back_populates="poll",
        cascade="all, delete-orphan",
        order_by="PollOption.sort_order",
    )

    def __repr__(self) -> str:
        return f"<Poll {self.id} status={self.status}>"


class PollOption(Base, TimestampMixin):
    __tablename__ = "poll_options"
    __table_args__ = (Index("ix_poll_options_poll", "poll_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    poll_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("polls.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vote_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    poll: Mapped[Poll] = relationship("Poll", back_populates="options")

    def __repr__(self) -> str:
        return f"<PollOption {self.text!r} votes={self.vote_count}>"


class Question(Base, TimestampMixin):
    """An anonymous, audience-submitted Q&A question. No approval queue -
    visible immediately; organizer can hide/delete after the fact."""

    __tablename__ = "questions"
    __table_args__ = (Index("ix_questions_event", "event_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional display name - still anonymous if left blank, no account required
    author_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    upvotes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_answered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return f"<Question {self.id} upvotes={self.upvotes}>"
