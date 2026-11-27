"""Compare what the tests evaluated with what Flagsmith serves in production."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from flagcov.recorder import Record

OPERATORS = {
    "EQUAL": "==",
    "NOT_EQUAL": "!=",
    "GREATER_THAN": ">",
    "GREATER_THAN_INCLUSIVE": ">=",
    "LESS_THAN": "<",
    "LESS_THAN_INCLUSIVE": "<=",
    "CONTAINS": "contains",
    "NOT_CONTAINS": "does not contain",
    "REGEX": "matches",
    "IN": "in",
    "IS_SET": "is set",
    "IS_NOT_SET": "is not set",
    "MODULO": "mod",
    "PERCENTAGE_SPLIT": "% split",
}


@dataclass
class FlagState:
    flag: str
    kind: str  # default | variant | segment | identity | kill_switch
    enabled: bool
    value: Any
    weight: float | None = None  # share of production traffic, in percent
    variant_key: str | None = None
    segment: str | None = None
    rule: str | None = None
    identifier: str | None = None
    covered: bool = False
    hits: int = 0
    tests: list[str] = field(default_factory=list)
    targeting_verified: bool | None = None

    stale: bool = False  # no scanned code reads this flag, so there is no code path to test

    @property
    def required(self) -> bool:
        return self.kind != "kill_switch" and not self.stale

    @property
    def label(self) -> str:
        if self.kind == "kill_switch":
            return "off (kill switch)"
        if not self.enabled:
            return "off"
        if self.value is None:
            return "on"
        return _display(self.value)

    @property
    def where(self) -> str:
        if self.kind == "segment":
            return f'segment "{self.segment}" ({self.rule})'
        if self.kind == "identity":
            return f'identity override "{self.identifier}"'
        if self.kind == "kill_switch":
            return "used when someone turns the flag off"
        return f"{_pct(self.weight)} of prod traffic"


@dataclass
class FlagSummary:
    flag: str
    evaluated: bool
    states: list[FlagState]
    stale: bool = False

    @property
    def untested_traffic(self) -> float:
        """Percent of this flag's default population that lands on an untested state."""
        if self.stale:
            return 0.0
        population = [s for s in self.states if s.kind in ("default", "variant") and s.weight is not None]
        return sum(s.weight or 0 for s in population if not s.covered)

    @property
    def untested_rules(self) -> list[FlagState]:
        return [s for s in self.states if s.kind in ("segment", "identity") and not s.covered]


@dataclass
class Report:
    flags: list[FlagSummary]
    environment: str = ""
    unknown_flags: dict[str, list[str]] = field(default_factory=dict)  # read in code, missing in Flagsmith
    unreferenced_flags: list[str] = field(default_factory=list)  # in Flagsmith, never read in code
    records: int = 0

    @property
    def states(self) -> list[FlagState]:
        return [s for f in self.flags for s in f.states]

    @property
    def required_states(self) -> list[FlagState]:
        return [s for s in self.states if s.required]

    @property
    def state_coverage(self) -> float:
        req = self.required_states
        return 100.0 if not req else 100.0 * sum(s.covered for s in req) / len(req)

    @property
    def live_flags(self) -> list[FlagSummary]:
        return [f for f in self.flags if not f.stale]

    @property
    def fully_tested(self) -> list[FlagSummary]:
        return [f for f in self.live_flags if f.untested_traffic == 0 and not f.untested_rules]

    @property
    def untested_traffic(self) -> float:
        """Worst case: the largest share of one flag's production traffic that hits untested code."""
        return max((f.untested_traffic for f in self.live_flags), default=0.0)

    @property
    def worst_flag(self) -> FlagSummary | None:
        return max(self.flags, key=lambda f: f.untested_traffic, default=None)

    @property
    def never_evaluated(self) -> list[str]:
        return [f.flag for f in self.flags if not f.evaluated]

    def to_dict(self) -> dict[str, Any]:
        return {
            "environment": self.environment,
            "records": self.records,
            "state_coverage": round(self.state_coverage, 2),
            "untested_traffic": round(self.untested_traffic, 2),
            "fully_tested_flags": len(self.fully_tested),
            "live_flags": len(self.live_flags),
            "never_evaluated": self.never_evaluated,
            "unknown_flags": self.unknown_flags,
            "unreferenced_flags": self.unreferenced_flags,
            "flags": [
                {
                    "flag": f.flag,
                    "evaluated": f.evaluated,
                    "untested_traffic": f.untested_traffic,
                    "states": [
                        {
                            "kind": s.kind,
                            "label": s.label,
                            "where": s.where,
                            "enabled": s.enabled,
                            "value": s.value,
                            "weight": s.weight,
                            "segment": s.segment,
                            "rule": s.rule,
                            "identifier": s.identifier,
                            "covered": s.covered,
                            "hits": s.hits,
                            "tests": s.tests[:5],
                            "targeting_verified": s.targeting_verified,
                        }
                        for s in f.states
                    ],
                }
                for f in self.flags
            ],
        }


# --------------------------------------------------------------------------- states


def extract_states(doc: dict[str, Any]) -> dict[str, list[FlagState]]:
    """Every flag state production can serve, from an environment document."""
    states: dict[str, list[FlagState]] = {}

    for fs in doc.get("feature_states", []):
        name = fs["feature"]["name"]
        enabled = bool(fs.get("enabled"))
        variants = fs.get("multivariate_feature_state_values") or []
        flag_states = states.setdefault(name, [])
        if enabled and variants:
            control = max(0.0, 100.0 - sum(float(v.get("percentage_allocation") or 0) for v in variants))
            flag_states.append(FlagState(name, "default", True, fs.get("feature_state_value"), weight=control, variant_key="control"))
            for v in sorted(variants, key=lambda v: v.get("id") or 0):
                option = v.get("multivariate_feature_option") or {}
                flag_states.append(
                    FlagState(
                        name,
                        "variant",
                        True,
                        option.get("value"),
                        weight=float(v.get("percentage_allocation") or 0),
                        variant_key=option.get("key"),
                    )
                )
        else:
            flag_states.append(FlagState(name, "default", enabled, fs.get("feature_state_value"), weight=100.0))
        if enabled:
            flag_states.append(FlagState(name, "kill_switch", False, None))

    for segment in (doc.get("project") or {}).get("segments", []):
        rule = describe_rules(segment.get("rules") or [])
        for fs in segment.get("feature_states") or []:
            name = fs["feature"]["name"]
            states.setdefault(name, []).append(
                FlagState(name, "segment", bool(fs.get("enabled")), fs.get("feature_state_value"), segment=segment.get("name"), rule=rule)
            )

    for override in doc.get("identity_overrides") or []:
        for fs in override.get("identity_features") or []:
            name = fs["feature"]["name"]
            states.setdefault(name, []).append(
                FlagState(name, "identity", bool(fs.get("enabled")), fs.get("feature_state_value"), identifier=override.get("identifier"))
            )

    for name, flag_states in states.items():
        states[name] = _dedupe(flag_states)
    return states


def _dedupe(flag_states: list[FlagState]) -> list[FlagState]:
    seen: set[tuple[Any, ...]] = set()
    out = []
    for s in flag_states:
        key = (s.kind, s.enabled, _norm(s.value), s.segment, s.identifier, s.variant_key)
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


def describe_rules(rules: list[dict[str, Any]]) -> str:
    parts = [_describe_rule(r) for r in rules]
    parts = [p for p in parts if p]
    return " AND ".join(parts) if parts else "always"


def _describe_rule(rule: dict[str, Any]) -> str:
    items = [_describe_condition(c) for c in rule.get("conditions") or []]
    items += [f"({x})" if " " in x and ("AND" in x or "OR" in x) else x for x in (_describe_rule(r) for r in rule.get("rules") or []) if x]
    if not items:
        return ""
    rule_type = (rule.get("type") or "ALL").upper()
    if rule_type == "ANY":
        return " OR ".join(items)
    if rule_type == "NONE":
        return "NOT (" + " OR ".join(items) + ")"
    return " AND ".join(items)


def _describe_condition(condition: dict[str, Any]) -> str:
    prop = condition.get("property_") or condition.get("property") or "?"
    op = condition.get("operator") or "EQUAL"
    value = condition.get("value")
    symbol = OPERATORS.get(op, op.lower())
    if op in ("IS_SET", "IS_NOT_SET"):
        return f"{prop} {symbol}"
    if op == "PERCENTAGE_SPLIT":
        return f"{value}% of identities"
    return f"{prop} {symbol} {value}"


# --------------------------------------------------------------------------- matching


def _norm(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def matches(state: FlagState, record: Record) -> bool:
    """Did this evaluation exercise the code path behind this flag state?"""
    if record.flag != state.flag:
        return False
    if record.value_type == "boolean":
        if state.kind == "kill_switch" or not state.enabled:
            return record.value is False
        # A boolean read only tells us the flag was on, not which variant was served,
        # so it covers simple on/off flags but never a multivariate value.
        return record.value is True and state.kind == "default" and state.weight == 100.0
    if state.kind == "kill_switch" or not state.enabled:
        # Disabled flags fall back to the default value written in the code.
        return record.reason == "DISABLED" or (
            record.default_value is not None and _norm(record.value) == _norm(record.default_value) and record.variant in (None, "")
            and record.source != "flagsmith"
        )
    if state.kind == "identity" and record.targeting_key != state.identifier:
        return False
    return _norm(record.value) == _norm(state.value)


class _SegmentMatcher:
    """Uses Flagsmith's own engine (when installed) to check segment targeting."""

    def __init__(self, doc: dict[str, Any]) -> None:
        self._context = None
        self._cache: dict[tuple[Any, ...], set[str]] = {}
        try:
            from flag_engine.engine import get_evaluation_result  # noqa: F401
            from flagsmith.mappers import map_environment_document_to_context

            self._context = map_environment_document_to_context(doc)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001 - engine missing or document too old/new: targeting stays unknown
            self._context = None

    @property
    def available(self) -> bool:
        return self._context is not None

    def segments_for(self, record: Record) -> set[str] | None:
        if self._context is None or not (record.targeting_key or record.traits):
            return None
        key = (record.targeting_key, tuple(sorted((k, _norm(v)) for k, v in record.traits.items())))
        if key not in self._cache:
            from flag_engine.engine import get_evaluation_result

            context = {
                **self._context,
                "identity": {"identifier": record.targeting_key or "flagcov-anonymous", "traits": dict(record.traits)},
            }
            try:
                result = get_evaluation_result(context)  # type: ignore[arg-type]
                self._cache[key] = {s["name"] for s in result.get("segments", [])}
            except Exception:  # noqa: BLE001
                self._cache[key] = set()
        return self._cache[key]


def analyze(
    doc: dict[str, Any],
    records: Iterable[Record],
    referenced_flags: dict[str, list[str]] | None = None,
) -> Report:
    """Build a coverage report.

    ``referenced_flags`` (optional, from :mod:`flagcov.scan`) maps flag keys found
    in source code to their locations; it enables the unknown/unreferenced checks.
    """
    records = list(records)
    by_flag: dict[str, list[Record]] = {}
    for r in records:
        by_flag.setdefault(r.flag, []).append(r)

    matcher = _SegmentMatcher(doc)
    summaries = []
    for name, flag_states in sorted(extract_states(doc).items()):
        flag_records = by_flag.get(name, [])
        for state in flag_states:
            for r in flag_records:
                if matches(state, r):
                    state.covered = True
                    state.hits += 1
                    if r.test and r.test not in state.tests:
                        state.tests.append(r.test)
            if state.kind == "segment" and matcher.available:
                verified = False
                for r in flag_records:
                    segs = matcher.segments_for(r)
                    if segs and state.segment in segs:
                        verified = True
                        break
                state.targeting_verified = verified
        summaries.append(FlagSummary(name, evaluated=bool(flag_records), states=flag_states))

    report = Report(flags=summaries, environment=str(doc.get("name") or ""), records=len(records))
    if referenced_flags is not None:
        known = {f.flag for f in summaries}
        report.unknown_flags = {k: v for k, v in sorted(referenced_flags.items()) if k not in known}
        report.unreferenced_flags = sorted(known - set(referenced_flags))
        for f in summaries:
            if f.flag in report.unreferenced_flags and not f.evaluated:
                f.stale = True
                for s in f.states:
                    s.stale = True
    return report


def _display(value: Any) -> str:
    text = _norm(value)
    return text if len(text) <= 24 else text[:21] + "..."


def _pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.0f}%" if float(value).is_integer() else f"{value:.1f}%"
