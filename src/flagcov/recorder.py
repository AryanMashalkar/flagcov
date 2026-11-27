"""Record every flag evaluation made while tests run.

Two capture paths, so teams are covered whichever way they read flags:

* an OpenFeature API-level hook (works with any provider, including the
  Flagsmith provider and OpenFeature's InMemoryProvider used in tests), and
* a thin instrumentation of the native Flagsmith Python SDK ``Flags`` object
  (``is_feature_enabled`` / ``get_feature_value``).
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Record:
    flag: str
    value: Any
    value_type: str  # boolean | string | integer | float | object | value
    variant: str | None = None
    reason: str | None = None
    default_value: Any = None
    targeting_key: str | None = None
    traits: dict[str, Any] = field(default_factory=dict)
    source: str = "openfeature"  # openfeature | flagsmith
    test: str | None = None


class Recorder:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.records: list[Record] = []
        self.current_test: str | None = None

    def add(self, record: Record) -> None:
        if record.test is None:
            record.test = self.current_test
        with self._lock:
            self.records.append(record)

    def clear(self) -> None:
        with self._lock:
            self.records.clear()

    def dump(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps([asdict(r) for r in self.records], indent=1, default=_jsonable), encoding="utf-8")

    @staticmethod
    def load(path: str | Path) -> list[Record]:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return [Record(**item) for item in data]


def _jsonable(value: Any) -> Any:
    if hasattr(value, "value"):  # enums such as Reason / FlagType
        return value.value
    return str(value)


recorder = Recorder()


# --------------------------------------------------------------------------- OpenFeature


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def make_openfeature_hook(target: Recorder | None = None):
    """Return an OpenFeature ``Hook`` instance that records evaluations."""
    from openfeature.hook import Hook

    rec = target or recorder

    class FlagCovHook(Hook):
        def after(self, hook_context, details, hints):  # noqa: ANN001
            ctx = hook_context.evaluation_context
            attributes = dict(getattr(ctx, "attributes", None) or {})
            rec.add(
                Record(
                    flag=hook_context.flag_key,
                    value=details.value,
                    value_type=str(_enum_value(hook_context.flag_type)).lower(),
                    variant=details.variant,
                    reason=None if details.reason is None else str(_enum_value(details.reason)),
                    default_value=hook_context.default_value,
                    targeting_key=getattr(ctx, "targeting_key", None),
                    traits={k: v for k, v in attributes.items() if isinstance(v, (str, int, float, bool))},
                    source="openfeature",
                )
            )

    return FlagCovHook()


def install_openfeature_hook() -> bool:
    """Register the recording hook globally. Returns False if OpenFeature isn't installed."""
    try:
        from openfeature import api
    except ImportError:
        return False
    if not any(type(h).__name__ == "FlagCovHook" for h in api.get_hooks()):
        api.add_hooks([make_openfeature_hook()])
    return True


# --------------------------------------------------------------------------- Flagsmith SDK

_original_flag_methods: dict[str, Any] = {}


def instrument_flagsmith_sdk() -> bool:
    """Patch ``flagsmith.models.Flags`` so direct SDK reads are recorded too."""
    try:
        from flagsmith.models import Flags
    except ImportError:
        return False
    if _original_flag_methods:
        return True

    original_enabled = Flags.is_feature_enabled
    original_value = Flags.get_feature_value
    _original_flag_methods.update(is_feature_enabled=original_enabled, get_feature_value=original_value)

    def _identity(flags: Any) -> tuple[str | None, dict[str, Any]]:
        identity = getattr(flags, "_flagcov_identity", None) or (None, {})
        return identity

    def is_feature_enabled(self, feature_name: str) -> bool:  # noqa: ANN001
        result = original_enabled(self, feature_name)
        key, traits = _identity(self)
        recorder.add(Record(flag=feature_name, value=result, value_type="boolean", targeting_key=key, traits=traits, source="flagsmith"))
        return result

    def get_feature_value(self, feature_name: str):  # noqa: ANN001, ANN202
        result = original_value(self, feature_name)
        key, traits = _identity(self)
        recorder.add(Record(flag=feature_name, value=result, value_type="value", targeting_key=key, traits=traits, source="flagsmith"))
        return result

    Flags.is_feature_enabled = is_feature_enabled  # type: ignore[method-assign]
    Flags.get_feature_value = get_feature_value  # type: ignore[method-assign]

    # Remember who the flags were evaluated for, so segment targeting can be verified.
    try:
        from flagsmith import Flagsmith

        original_identity_flags = Flagsmith.get_identity_flags
        _original_flag_methods["get_identity_flags"] = original_identity_flags

        def get_identity_flags(self, identifier, traits=None, **kwargs):  # noqa: ANN001, ANN202
            flags = original_identity_flags(self, identifier, traits, **kwargs)
            plain = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in (traits or {}).items()}
            try:
                flags._flagcov_identity = (identifier, plain)
            except AttributeError:
                pass
            return flags

        Flagsmith.get_identity_flags = get_identity_flags  # type: ignore[method-assign]
    except ImportError:  # pragma: no cover
        pass
    return True


def uninstrument_flagsmith_sdk() -> None:
    if not _original_flag_methods:
        return
    from flagsmith import Flagsmith
    from flagsmith.models import Flags

    Flags.is_feature_enabled = _original_flag_methods["is_feature_enabled"]  # type: ignore[method-assign]
    Flags.get_feature_value = _original_flag_methods["get_feature_value"]  # type: ignore[method-assign]
    if "get_identity_flags" in _original_flag_methods:
        Flagsmith.get_identity_flags = _original_flag_methods["get_identity_flags"]  # type: ignore[method-assign]
    _original_flag_methods.clear()
