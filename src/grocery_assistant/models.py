"""Core data models for Grocery Assistant."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Optional


@dataclass
class IntakeEvent:
    raw_text: str
    source_channel: str  # 'discord' | 'sms' | 'cli'
    sender: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: Optional[int] = None


@dataclass
class GroceryItem:
    name: str           # original name as parsed
    canonical: str      # normalized form for dedup
    category: str = "other"
    quantity: Optional[str] = None
    unit: Optional[str] = None
    notes: Optional[str] = None
    status: str = "pending"  # pending | reviewed | drafted | ordered
    ambiguous: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: Optional[int] = None

    def is_pending(self) -> bool:
        return self.status == "pending"


@dataclass
class ParsedItem:
    """Intermediate result from normalizer before DB persistence."""
    raw: str
    canonical: str
    quantity: Optional[str]
    unit: Optional[str]
    notes: Optional[str]
    category: str
    ambiguous: bool
    ambiguity_reason: Optional[str] = None


@dataclass
class CartSession:
    id: Optional[int] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    status: str = "draft"  # draft | needs_clarification | awaiting_approval | approved | cancelled
    item_ids: list = field(default_factory=list)


@dataclass
class Approval:
    session_id: int
    approved_by: str
    approval_phrase: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: Optional[int] = None
