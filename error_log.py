"""Small, rotating diagnostic log that never writes exception messages or input data."""

from datetime import datetime, timezone
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import threading
import traceback


LOG_PATH = Path(__file__).resolve().parent / "logs" / "gherkin-errors.log"
_WRITE_LOCK = threading.Lock()


def log_error(
    operation: str, error: BaseException, *, path: Path | None = None,
    max_bytes: int = 1_000_000, backup_count: int = 3,
) -> None:
    """Record error types and code locations, but not messages or local variables."""
    lines = [f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} | {operation}"]
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        lines.append(f"  {type(current).__name__}")
        for frame in traceback.extract_tb(current.__traceback__):
            lines.append(f"    {Path(frame.filename).name}:{frame.lineno} in {frame.name}")
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    record = logging.LogRecord("gherkin", logging.ERROR, __file__, 0, "\n".join(lines) + "\n", (), None)
    destination = LOG_PATH if path is None else Path(path)
    try:
        with _WRITE_LOCK:
            destination.parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(
                destination, maxBytes=max_bytes, backupCount=backup_count,
                encoding="utf-8", delay=True,
            )
            try:
                handler.emit(record)
            finally:
                handler.close()
    except OSError:
        # A logging failure must never hide the error the user is troubleshooting.
        pass
