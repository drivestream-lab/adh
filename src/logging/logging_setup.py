"""Logging setup module for Parichay."""

import atexit
import json as _json
import logging
import os
import sys
import threading
import uuid
from datetime import UTC, datetime
from typing import Any, Callable, Optional

from loguru import logger

from src.logging.logging_context import get_correlation_id

is_logging_shutdown = False
_logging_lock = threading.RLock()
_is_logging_setup = False

_SERVICE_NAME = "adh"

TEXT_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "{message}"
)

FILE_TEXT_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | " "{level: <8} | " "{name}:{function}:{line} | " "{message}"
)


def _flat_json_line(record: Any, service: str, environment: str) -> str:
    """One flat JSON object per line; record is loguru's runtime dict-like record."""
    output: dict[str, Any] = {
        "timestamp": record["time"].isoformat(),
        "level": record["level"].name,
        "message": record["message"],
        "service": service,
        "environment": environment,
        "logger": record["name"],
        "function": record["function"],
        "line": record["line"],
    }
    for key, value in record["extra"].items():
        if key not in output:
            output[key] = value
    output["service"] = service
    output["environment"] = environment
    return _json.dumps(output, default=str) + "\n"


def _make_flat_json_sink(
    service: str, environment: str, writer: Callable[[str], None]
) -> Callable[[Any], None]:
    """Write one flat JSON line per log record."""

    def sink(message: Any) -> None:
        writer(_flat_json_line(message.record, service, environment))

    return sink


def _context_patcher(record: Any) -> None:
    """Inject per-request correlation_id from contextvar into every log record."""
    cid = get_correlation_id()
    if cid:
        record["extra"]["correlation_id"] = cid


class ResilientSink:
    """A sink that is resilient to program shutdown conditions."""

    def __init__(self, sink: Any) -> None:
        self.sink = sink
        self.errors = 0
        self.max_errors = 10

    def write(self, message: str) -> None:
        global is_logging_shutdown
        if is_logging_shutdown:
            return
        try:
            self.sink.write(message)
        except (ValueError, IOError) as e:
            if "closed file" in str(e).lower() or "closed stream" in str(e).lower():
                self.errors += 1
                if self.errors >= self.max_errors:
                    with _logging_lock:
                        is_logging_shutdown = True
            else:
                try:
                    sys.stderr.write(f"Logging error: {e}\n")
                except Exception:
                    pass


def shutdown_logging() -> None:
    """Safely shut down logging system."""
    global is_logging_shutdown
    with _logging_lock:
        if is_logging_shutdown:
            return
        is_logging_shutdown = True
    logger.remove()
    try:
        logger.add(sys.stderr, level="CRITICAL", format="{message}", enqueue=False)
    except Exception:
        pass


class InterceptHandler(logging.Handler):
    """Redirect stdlib logging records into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno  # type: ignore[assignment]
        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _stdlib_log_level(log_level: str) -> int:
    """Map APP log level string to ``logging`` module level."""
    return getattr(logging, log_level.upper(), logging.INFO)


def setup_logging(settings: Optional[Any] = None) -> None:
    """Configure loguru sinks driven by AppSettings.

    When log_format='json' (production), each log line is one JSON object with
    top-level fields: service, environment, level, message, timestamp, correlation_id
    plus any kwargs passed to the log call.

    When log_format='text' (default / local dev), human-readable colored output is used.
    """
    global _is_logging_setup

    with _logging_lock:
        if _is_logging_setup:
            return

        atexit.register(shutdown_logging)
        logger.remove()

        log_level = "INFO"
        log_format = "text"
        is_development = True
        log_to_console = True
        log_dir = "logs"
        environment = "development"

        if settings is not None:
            log_level = getattr(settings, "log_level", log_level)
            log_format = getattr(settings, "log_format", log_format)
            is_development = getattr(settings, "is_development", is_development)
            log_to_console = getattr(settings, "log_to_console", log_to_console)
            log_dir = getattr(settings, "log_dir", log_dir)
            env_val = getattr(settings, "environment", None)
            if env_val is not None:
                environment = env_val.value if hasattr(env_val, "value") else str(env_val)

        startup_correlation_id = get_correlation_id() or str(uuid.uuid4())
        os.makedirs(log_dir, exist_ok=True)

        use_json = log_format.lower() == "json"

        if use_json:
            service = _SERVICE_NAME
            log_file_path = os.path.join(
                log_dir, f"adh_{datetime.now(UTC).strftime('%Y%m%d')}.log"
            )

            def _append_json_line(line: str) -> None:
                with open(log_file_path, "a", encoding="utf-8") as log_file:
                    log_file.write(line)

            logger.add(
                _make_flat_json_sink(
                    service=service, environment=environment, writer=_append_json_line
                ),
                level=log_level,
                enqueue=True,
            )
            if log_to_console:
                stdout_sink = ResilientSink(sys.stdout)
                logger.add(
                    _make_flat_json_sink(
                        service=service, environment=environment, writer=stdout_sink.write
                    ),
                    level=log_level,
                    enqueue=True,
                )
        else:
            log_file_path = os.path.join(
                log_dir, f"adh_{datetime.now(UTC).strftime('%Y%m%d')}.log"
            )
            logger.add(
                log_file_path,
                rotation="00:00",
                retention="30 days",
                compression="gz",
                level=log_level,
                format=FILE_TEXT_FORMAT,
                backtrace=True,
                diagnose=is_development,
                enqueue=True,
            )
            if log_to_console:
                stdout_sink = ResilientSink(sys.stdout)
                logger.add(
                    stdout_sink.write,
                    level=log_level,
                    format=TEXT_FORMAT,
                    backtrace=True,
                    diagnose=is_development,
                    enqueue=True,
                    colorize=is_development,
                )

        logger.configure(
            patcher=_context_patcher,
            extra={
                "service": _SERVICE_NAME,
                "environment": environment,
                "correlation_id": startup_correlation_id,
            },
        )

        root_logger = logging.getLogger()
        root_logger.handlers = []
        root_logger.addHandler(InterceptHandler())
        root_logger.setLevel(_stdlib_log_level(log_level))
        logging.getLogger("watchfiles").setLevel(logging.WARNING)

        logger.info(
            "Logging initialized",
            log_level=log_level,
            log_format=log_format,
            environment=environment,
        )
        _is_logging_setup = True


def get_logger() -> Any:
    """Get the loguru logger instance."""
    return logger
