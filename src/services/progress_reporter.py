"""Progress reporting helpers for services with legacy CLI output."""


class ProgressReporter:
    """Default reporter that preserves existing CLI output."""

    def emit(self, message: str = "") -> None:
        print(message)


class NullProgressReporter:
    """Reporter for non-interactive callers and focused unit tests."""

    def emit(self, message: str = "") -> None:
        return None
