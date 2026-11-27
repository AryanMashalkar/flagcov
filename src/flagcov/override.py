"""Force a flag to a given state inside one test, through OpenFeature.

Used by the ``flag_override`` pytest fixture and by the test stubs FlagCov
generates. It patches the *current provider instance* for the duration of a test
(no provider re-registration), so it works with the Flagsmith provider,
OpenFeature's InMemoryProvider, or any other provider.
"""

from __future__ import annotations

from typing import Any


class _Off:
    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return "flagcov.OFF"


#: Pass as the value to simulate the flag being turned off (the kill-switch path).
OFF = _Off()

_METHODS = (
    "resolve_boolean_details",
    "resolve_string_details",
    "resolve_integer_details",
    "resolve_float_details",
    "resolve_object_details",
)


class FlagOverrides:
    def __init__(self) -> None:
        self._values: dict[int, dict[str, Any]] = {}
        self._patched: list[tuple[Any, str, Any]] = []

    def set(self, flag: str, value: Any, domain: str | None = None) -> None:
        from openfeature.provider._registry import provider_registry

        provider = provider_registry.get_provider(domain)
        table = self._values.get(id(provider))
        if table is None:
            table = self._values[id(provider)] = {}
            self._patch(provider, table)
        table[flag] = value

    def _patch(self, provider: Any, table: dict[str, Any]) -> None:
        from openfeature.flag_evaluation import FlagResolutionDetails, Reason

        for name in _METHODS:
            original = getattr(provider, name, None)
            if original is None:
                continue

            def wrapper(flag_key, default_value, evaluation_context=None, *args, _original=original, **kwargs):  # noqa: ANN001, ANN202
                if flag_key in table:
                    value = table[flag_key]
                    if value is OFF:
                        return FlagResolutionDetails(value=default_value, reason=Reason.DISABLED)
                    return FlagResolutionDetails(value=value, reason=Reason.STATIC, variant="flagcov-override")
                return _original(flag_key, default_value, evaluation_context, *args, **kwargs)

            had_own = name in vars(provider)
            self._patched.append((provider, name, original if had_own else None))
            setattr(provider, name, wrapper)

    def restore(self) -> None:
        for provider, name, original in reversed(self._patched):
            if original is None:
                try:
                    delattr(provider, name)
                except AttributeError:  # pragma: no cover
                    pass
            else:
                setattr(provider, name, original)
        self._patched.clear()
        self._values.clear()
