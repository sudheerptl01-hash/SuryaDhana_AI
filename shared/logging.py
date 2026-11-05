from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar, Token
from typing import Any

import structlog

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
_configured: dict[str, bool] = {"done": False}


def get_correlation_id() -> str:
    cid = _correlation_id.get()
    return cid if cid else "no-correlation-id"


def set_correlation_id(cid: str | None = None) -> str:
    cid = cid or str(uuid.uuid4())
    _correlation_id.set(cid)
    return cid


def bind_correlation_id(cid: str | None = None) -> Token[str]:
    """Bind a correlation id for the current task/thread context and return the token that undoes it
    (``unbind_correlation_id``). The request-id middleware in ``shared.metrics`` uses this pair so an id never
    leaks from one request into the next on a reused worker."""
    return _correlation_id.set(cid or str(uuid.uuid4()))


def unbind_correlation_id(token: Token[str]) -> None:
    try:
        _correlation_id.reset(token)
    except ValueError:  # token from another context (a thread hop): fall back to clearing
        _correlation_id.set("")


def is_logging_configured() -> bool:
    """True once ``configure_logging`` ran in this process (the services call it in their lifespan; ui-api did not
    until the observability middleware, which configures it on install when nobody has)."""
    return _configured["done"]


def _add_correlation_id(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    event_dict["correlation_id"] = get_correlation_id()
    return event_dict


def _add_service_name(service: str):
    def processor(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        event_dict["service"] = service
        return event_dict
    return processor


def configure_logging(service_name: str, log_level: str = "INFO") -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _add_correlation_id,
            _add_service_name(service_name),
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    _configured["done"] = True


def get_logger(name: str) -> structlog.BoundLogger:
    return structlog.get_logger(name)
