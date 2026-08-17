"""Exception types raised by PipelineGuard.

These sit on top of (not instead of) the exceptions raised by the
`rocketride` SDK itself (`RocketRideException`, `ExecutionException`,
`PipeException`, `AuthenticationException`, etc). PipelineGuard catches
those and wraps its own decisions around them.
"""


class PipelineGuardError(Exception):
    """Base class for all PipelineGuard-specific errors."""


class AllVariantsFailedError(PipelineGuardError):
    """Raised when every configured variant failed for a given run.

    Attributes:
        attempts: ordered list of RunAttempt records, one per variant tried.
    """

    def __init__(self, message: str, attempts=None):
        super().__init__(message)
        self.attempts = attempts or []
