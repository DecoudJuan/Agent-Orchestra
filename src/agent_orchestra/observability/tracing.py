from __future__ import annotations

from contextlib import contextmanager
from typing import Any


try:
    from langfuse import get_client, observe, propagate_attributes
    from langfuse.openai import OpenAI as LangfuseOpenAI
except Exception:
    get_client = None
    propagate_attributes = None
    LangfuseOpenAI = None

    def observe(*args, **kwargs):
        def decorator(func):
            return func

        return decorator


def get_openai_client():
    if LangfuseOpenAI is not None:
        return LangfuseOpenAI()

    from openai import OpenAI

    return OpenAI()


def flush_traces() -> None:
    if get_client is None:
        return
    try:
        get_client().flush()
    except Exception:
        pass


def mark_error(message: str) -> None:
    if get_client is None:
        return
    try:
        get_client().update_current_span(level="ERROR", status_message=message)
    except Exception:
        pass


def update_current_span(**kwargs: Any) -> None:
    if get_client is None:
        return
    try:
        get_client().update_current_span(**kwargs)
    except Exception:
        pass


def update_current_trace(**kwargs: Any) -> None:
    if get_client is None:
        return
    try:
        get_client().update_current_trace(**kwargs)
    except Exception:
        pass


@contextmanager
def trace_attributes(**kwargs: Any):
    if propagate_attributes is None:
        yield
        return

    with propagate_attributes(**kwargs):
        yield


@contextmanager
def retriever_observation(name: str, *, input: Any = None):
    if get_client is None:
        yield None
        return

    try:
        with get_client().start_as_current_observation(
            as_type="retriever",
            name=name,
            input=input,
        ) as observation:
            yield observation
    except Exception:
        yield None
