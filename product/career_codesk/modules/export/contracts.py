"""Published local mock-outbox interface."""

from typing import Protocol


class ExportGateway(Protocol):
    """Describes a local-only export adapter; delivery workflows are deferred."""

    def destination(self) -> str:
        """Name the only permitted destination for this foundation adapter."""


class LocalMockOutbox:
    backend = "in_process_mock"

    def destination(self) -> str:
        return "local-mock-outbox"
