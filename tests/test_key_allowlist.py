"""D1: the key's white list is checked before the money moves."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import BadParameterError, InsufficientFundsError
from app.core.models import AccountInfo, GenerationRequest, ModelInfo
from app.services.generation_service import GenerationService
from app.services.history_store import HistoryStore


class _Provider:
    def __init__(self, account: AccountInfo) -> None:
        self.account = account
        self.checks = 0
        self.generated = 0

    def check_account(self) -> AccountInfo:
        self.checks += 1
        return self.account

    def generate(self, request: GenerationRequest, **_):
        self.generated += 1
        from app.core.models import GeneratedImage, GenerationResult

        return GenerationResult(
            images=[GeneratedImage(data=b"\x89PNG", media_type="image/png")],
            cost_rub=1.0,
            balance=None,
            model=request.model,
        )


def _service(tmp_path: Path, provider: _Provider) -> GenerationService:
    import app.services.generation_service as gs

    gs.create_provider = lambda provider_id, api_key: provider  # type: ignore[assignment]
    return GenerationService(HistoryStore(tmp_path / "history.json"))


@pytest.fixture
def save_dir(tmp_path: Path) -> Path:
    return tmp_path


def _model(price: float | None = 1.0) -> ModelInfo:
    return ModelInfo(provider_id="aitunnel", id="gpt-image-1", max_price=price)


def _request(model: str = "gpt-image-1") -> GenerationRequest:
    return GenerationRequest(provider_id="aitunnel", model=model, prompt="a cat")


def _run(tmp_path: Path, provider: _Provider, model: str = "gpt-image-1", price=1.0):
    service = _service(tmp_path, provider)
    return service.generate(
        _request(model),
        _model(price),
        save_dir=tmp_path,
        api_key="k",
        check_balance_first=True,
    )


class TestAModelTheKeyMayNotUse:
    def test_it_is_refused_before_anything_is_sent(self, tmp_path: Path) -> None:
        provider = _Provider(
            AccountInfo(balance=100.0, limits={"allowed_models": ["other-model"]})
        )

        with pytest.raises(BadParameterError) as caught:
            _run(tmp_path, provider)

        assert "gpt-image-1" in str(caught.value)
        assert "other-model" in str(caught.value)
        assert provider.generated == 0, "the request went out anyway"
        assert HistoryStore(tmp_path / "history.json").records() == []

    def test_the_check_needs_no_price(self, tmp_path: Path) -> None:
        """A priceless model is refused for the same reason."""
        provider = _Provider(
            AccountInfo(balance=100.0, limits={"allowed_models": ["other-model"]})
        )

        with pytest.raises(BadParameterError):
            _run(tmp_path, provider, price=None)

        assert provider.generated == 0

    def test_an_allowed_model_goes_through(self, tmp_path: Path) -> None:
        provider = _Provider(
            AccountInfo(balance=100.0, limits={"allowed_models": ["gpt-image-1", "dall-e"]})
        )

        _run(tmp_path, provider)

        assert provider.generated == 1

    def test_a_long_white_list_is_shortened(self, tmp_path: Path) -> None:
        allowed = [f"model-{index}" for index in range(40)]
        provider = _Provider(AccountInfo(balance=100.0, limits={"allowed_models": allowed}))

        with pytest.raises(BadParameterError) as caught:
            _run(tmp_path, provider)

        message = str(caught.value)
        assert "model-9" in message
        assert "model-10" not in message, "the list must not grow without bound"


class TestNoWhiteListMeansNoRefusal:
    def test_a_provider_that_reports_nothing_is_trusted(self, tmp_path: Path) -> None:
        provider = _Provider(AccountInfo(balance=100.0))

        _run(tmp_path, provider)

        assert provider.generated == 1

    def test_an_empty_white_list_blocks_everything(self, tmp_path: Path) -> None:
        """An explicitly empty list is a fact, not a missing one."""
        provider = _Provider(AccountInfo(balance=100.0, limits={"allowed_models": []}))

        with pytest.raises(BadParameterError):
            _run(tmp_path, provider)

        assert provider.generated == 0

    def test_a_white_list_of_the_wrong_type_is_ignored(self, tmp_path: Path) -> None:
        provider = _Provider(
            AccountInfo(balance=100.0, limits={"allowed_models": "gpt-image-1"})
        )

        _run(tmp_path, provider)

        assert provider.generated == 1


class TestOrderMatters:
    def test_the_model_is_checked_before_the_money(self, tmp_path: Path) -> None:
        """Both would be refused; the model is the one worth explaining first."""
        provider = _Provider(
            AccountInfo(balance=0.0, limits={"allowed_models": ["other-model"]})
        )

        with pytest.raises(BadParameterError):
            _run(tmp_path, provider)

    def test_the_money_is_still_checked_for_an_allowed_model(self, tmp_path: Path) -> None:
        provider = _Provider(
            AccountInfo(balance=0.0, limits={"allowed_models": ["gpt-image-1"]})
        )

        with pytest.raises(InsufficientFundsError):
            _run(tmp_path, provider)

        assert provider.generated == 0
