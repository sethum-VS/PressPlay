class PressPlayError(Exception):
    """Base application error."""


class ValidationError(PressPlayError):
    pass


class RateLimitError(PressPlayError):
    pass


class ConcurrentJobsError(PressPlayError):
    pass


class JobNotFoundError(PressPlayError):
    pass


class ResultsNotFoundError(PressPlayError):
    pass


class AuthError(PressPlayError):
    pass


class DownloadError(PressPlayError):
    """YouTube download or trim failed."""


class MemvidError(PressPlayError):
    """Memvid ingest or context extraction failed."""
