"""The session limit must cover the request, not only what was already spent,
and a request the key cannot pay for must not be sent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import InsufficientFundsError
from app.core.models import (
    AccountInfo,
    GeneratedImage,
    GenerationRequest,
    GenerationResult,
    ModelInfo,
)
from app.services.generation_service import GenerationService
from app.services.history_store import HistoryStore

PNG = b"\x89PNG\r\n\x1a\n" + b"y" * 24


def _request(n: int = 1) -> GenerationRequest:
    return GenerationRequest(provider_id="polza", model="tongyi-mai/z-image", prompt="x", n=n)


def _model(max_price: float | None = 1.4) -> ModelInfo:
    return ModelInfo(
        id="tongyi-mai/z-image",
        provider_id="polza",
        min_price=max_price,
        max_price=max_price,
        max_n=6,
    )


class _Provider:
    """A provider that reports a balance and would happily generate anyway."""

    def __init__(self, account: AccountInfo | None = None, fail_check: Exception | None = None):
        self.account = account or AccountInfo(balance=100.0)
        self.fail_check = fail_check
        self.generated = 0
        self.checks = 0

    def check_account(self, timeout: int = 30) -> AccountInfo:
        self.checks += 1
        if self.fail_check is not None:
            raise self.fail_check
        return self.account

    def generate(self, request, *, timeout=180, cancel_check=None) -> GenerationResult:
        self.generated += 1
        return GenerationResult(
            images=[GeneratedImage(data=PNG)],
            cost_rub=1.4,
            balance=None,
            model=request.model,
        )


def _service(tmp_path: Path, provider: _Provider) -> GenerationService:
    import app.services.generation_service as gs

    gs.create_provider = lambda provider_id, api_key: provider  # type: ignore[assignment]
    return GenerationService(HistoryStore(tmp_path / "history.json"))


class TestPreflightBalance:
    def test_a_request_the_balance_cannot_cover_is_not_sent(self, tmp_path: Path) -> None:
        provider = _Provider(AccountInfo(balance=0.5))
        service = _service(tmp_path, provider)

        with pytest.raises(InsufficientFundsError) as raised:
            service.generate(
                _request(n=1),
                _model(1.4),
                save_dir=tmp_path,
                api_key="k",
                check_balance_first=True,
            )

        assert provider.generated == 0, "the request went out anyway"
        assert "1.40" in str(raised.value)
        assert "0.50" in str(raised.value)

    def test_a_refused_request_leaves_no_history_entry(self, tmp_path: Path) -> None:
        """Nothing was sent and nothing was charged, so there is nothing to record."""
        service = _service(tmp_path, _Provider(AccountInfo(balance=0.5)))

        with pytest.raises(InsufficientFundsError):
            service.generate(
                _request(n=1),
                _model(1.4),
                save_dir=tmp_path,
                api_key="k",
                check_balance_first=True,
            )

        assert HistoryStore(tmp_path / "history.json").records() == []

    def test_a_batch_is_refused_before_the_first_task_is_paid(self, tmp_path: Path) -> None:
        """Polza charges task by task, so a half-funded batch loses money."""
        provider = _Provider(AccountInfo(balance=3.0))
        service = _service(tmp_path, provider)

        with pytest.raises(InsufficientFundsError):
            service.generate(
                _request(n=3),
                _model(1.4),
                save_dir=tmp_path,
                api_key="k",
                check_balance_first=True,
            )

        assert provider.generated == 0

    def test_an_affordable_request_goes_through(self, tmp_path: Path) -> None:
        provider = _Provider(AccountInfo(balance=10.0))
        service = _service(tmp_path, provider)

        outcome = service.generate(
            _request(n=1),
            _model(1.4),
            save_dir=tmp_path,
            api_key="k",
            check_balance_first=True,
        )

        assert provider.generated == 1
        assert len(outcome.file_paths) == 1
        assert outcome.account is not None
        assert outcome.account.balance == 10.0

    def test_the_key_budget_is_checked_too(self, tmp_path: Path) -> None:
        """AITUNNEL refused a request with plenty of balance but a small budget."""
        provider = _Provider(AccountInfo(balance=500.0, budget_remaining=0.64))
        service = _service(tmp_path, provider)

        with pytest.raises(InsufficientFundsError) as raised:
            service.generate(
                _request(n=1),
                _model(1.4),
                save_dir=tmp_path,
                api_key="k",
                check_balance_first=True,
            )

        assert provider.generated == 0
        assert "budget" in str(raised.value)

    def test_a_failing_balance_check_does_not_block_the_user(self, tmp_path: Path) -> None:
        """Our own check breaking is no reason to refuse; the aggregator decides."""
        from app.core.errors import ProviderError

        provider = _Provider(fail_check=ProviderError("network is down"))
        service = _service(tmp_path, provider)

        outcome = service.generate(
            _request(n=1),
            _model(1.4),
            save_dir=tmp_path,
            api_key="k",
            check_balance_first=True,
        )

        assert provider.generated == 1
        assert outcome.account is None

    def test_without_the_flag_nothing_is_asked(self, tmp_path: Path) -> None:
        """A model without a price has no estimate, so there is nothing to compare."""
        provider = _Provider(AccountInfo(balance=0.0))
        service = _service(tmp_path, provider)

        service.generate(
            _request(n=1),
            _model(None),
            save_dir=tmp_path,
            api_key="k",
            check_balance_first=True,
        )

        assert provider.checks == 0
        assert provider.generated == 1

    def test_the_check_is_off_by_default(self, tmp_path: Path) -> None:
        provider = _Provider(AccountInfo(balance=0.5))
        service = _service(tmp_path, provider)

        service.generate(_request(n=1), _model(1.4), save_dir=tmp_path, api_key="k")

        assert provider.checks == 0
        assert provider.generated == 1
