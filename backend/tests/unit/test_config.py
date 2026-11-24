from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings

_ENV_NAMES = ("MAX_UPLOAD_MB", "CORS_ORIGINS", "LOG_LEVEL", "DOCS_ENABLED")


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_defaults_without_env() -> None:
    settings = Settings(_env_file=None)

    assert settings.max_upload_mb == 100
    assert settings.max_upload_bytes == 104_857_600
    assert settings.cors_origins == ["http://localhost:5173"]
    assert settings.log_level == "INFO"
    assert settings.docs_enabled is True


def test_cors_origins_parsed_as_comma_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://a:1, http://b:2 ,")

    assert Settings(_env_file=None).cors_origins == ["http://a:1", "http://b:2"]


def test_empty_cors_origins_is_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "")

    assert Settings(_env_file=None).cors_origins == []


def test_unknown_keys_in_env_file_are_ignored(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("UNKNOWN_KEY=x\nMAX_UPLOAD_MB=5\n", encoding="utf-8")

    assert Settings(_env_file=env_file).max_upload_mb == 5


def test_env_example_is_compatible() -> None:
    settings = Settings(_env_file=Path(__file__).parents[2] / ".env.example")

    assert settings.max_upload_mb == 100
    assert settings.cors_origins == ["http://localhost:5173"]
    assert settings.log_level == "INFO"
    assert settings.docs_enabled is True


@pytest.mark.parametrize("value", ["0", "abc"])
def test_invalid_max_upload_mb_rejected(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("MAX_UPLOAD_MB", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_invalid_log_level_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "verbose")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_log_level_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "info")

    assert Settings(_env_file=None).log_level == "INFO"


@pytest.mark.parametrize(("value", "expected"), [("false", False), ("0", False), ("true", True)])
def test_docs_enabled_from_env(monkeypatch: pytest.MonkeyPatch, value: str, expected: bool) -> None:
    monkeypatch.setenv("DOCS_ENABLED", value)

    assert Settings(_env_file=None).docs_enabled is expected
