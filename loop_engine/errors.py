from __future__ import annotations

from typing import Any, Dict, Optional


class LoopError(Exception):
    """A typed error that is safe to show at the command-line seam."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        exit_code: int = 20,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


class ConfigError(LoopError):
    def __init__(self, code: str, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("exit_code", 70)
        super().__init__(code, message, **kwargs)


class PlanError(LoopError):
    def __init__(self, code: str, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("exit_code", 70)
        super().__init__(code, message, **kwargs)


class GitSafetyError(LoopError):
    def __init__(self, code: str, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("exit_code", 30)
        super().__init__(code, message, **kwargs)


class AgentError(LoopError):
    def __init__(self, code: str, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("exit_code", 40)
        super().__init__(code, message, **kwargs)


class RunFailed(LoopError):
    def __init__(self, code: str, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("exit_code", 50)
        super().__init__(code, message, **kwargs)
