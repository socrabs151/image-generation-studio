"""Domain models shared across the application.

These dataclasses are independent of Qt and of any concrete provider: providers
translate their raw API payloads into these types, and the UI consumes only them.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ModelInfo:
    """A single generation model as advertised by a provider catalog."""

    id: str
    provider_id: str
    description: str = ""
    min_price: float | None = None
    max_price: float | None = None
    resolutions: list[str] = field(default_factory=list)
    aspect_ratios: list[str] = field(default_factory=list)
    qualities: list[str] = field(default_factory=list)
    formats: list[str] = field(default_factory=list)
    backgrounds: list[str] = field(default_factory=list)
    supports_seed: bool = False
    supports_generation: bool = True
    supports_edit: bool = False
    max_n: int = 1
    max_input_references: int = 0
    allowed_passthrough: list[str] = field(default_factory=list)

    @property
    def price_range(self) -> bool:
        """Whether the model has a real price range (min differs from max)."""
        return (
            self.min_price is not None
            and self.max_price is not None
            and abs(self.max_price - self.min_price) > 0.005
        )

    def price_text(self) -> str:
        """Human-readable price label, e.g. ``0.85…42.50 ₽``."""
        from app.core.pricing import format_price

        return format_price(self.min_price, self.max_price)

    def display_name(self) -> str:
        """Dropdown label: ``model — provider — price — capabilities``."""
        bits: list[str] = []
        if self.resolutions:
            bits.append("/".join(self.resolutions[:4]))
        if self.max_input_references:
            bits.append(f"refs<={self.max_input_references}")
        if self.max_n > 1:
            bits.append(f"n<={self.max_n}")
        caps = ", ".join(bits) if bits else "—"
        return f"{self.id} — {self.provider_id} — {self.price_text()} — {caps}"


@dataclass(slots=True)
class GenerationRequest:
    """Parameters of a single generation call."""

    provider_id: str
    model: str
    prompt: str
    n: int = 1
    quality: str | None = None
    resolution: str | None = None
    aspect_ratio: str | None = None
    size: str | None = None
    output_format: str | None = None
    background: str | None = None
    seed: int | None = None
    input_references: list[bytes] = field(default_factory=list)
    passthrough: dict = field(default_factory=dict)


@dataclass(slots=True)
class GeneratedImage:
    """A single generated image."""

    data: bytes
    media_type: str | None = None


@dataclass(slots=True)
class GenerationResult:
    """Outcome of a generation call."""

    images: list[GeneratedImage]
    cost_rub: float | None
    balance: float | None
    model: str


@dataclass(slots=True)
class AccountInfo:
    """Balance and budget information for a provider key."""

    balance: float | None = None
    budget_initial: float | None = None
    budget_remaining: float | None = None
    email: str | None = None
    limits: dict = field(default_factory=dict)
