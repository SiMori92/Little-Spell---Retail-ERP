"""Shared, manifest-driven source boundary for file-backed operational facts."""

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping


class ImportRefused(ValueError):
    """A source cannot safely cross the import boundary."""


@dataclass(frozen=True)
class IntakeManifest:
    kind: str
    header: tuple[str, ...]
    optional_columns: tuple[str, ...]
    verified: bool
    actual_filename: re.Pattern[str]
    target_models: tuple[str, ...]
    events: tuple[str, ...]
    natural_key: str
    key_from: Callable[[dict], str] | None = None
    payload_builders: Mapping[str, Callable[..., dict]] = field(default_factory=dict)

    def payload_for(self, event_type: str, **context) -> dict:
        if event_type not in self.events or event_type not in self.payload_builders:
            raise ImportRefused(f"{self.kind} manifest has no payload builder for {event_type}")
        return self.payload_builders[event_type](**context)


def classify_filename(path: Path, dataset_kind: str, manifest: IntakeManifest) -> str:
    """Classify by name only. Never infer dataset provenance from CSV contents."""
    name = path.name
    if name.startswith("SAMPLE_") and name.endswith(".csv") and len(name) > len("SAMPLE_.csv"):
        kind = "SAMPLE"
    elif manifest.actual_filename.fullmatch(name):
        kind = "ACTUAL"
    else:
        raise ImportRefused(f"Unclassified {manifest.kind} filename: {name}")
    if kind != dataset_kind:
        raise ImportRefused(f"Filename {name} is {kind}; application dataset_kind is {dataset_kind}")
    return kind


def read_csv(path: Path, manifest: IntakeManifest) -> list[dict]:
    """Accept only a declared header variant, preserving column order."""
    try:
        with path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            observed = reader.fieldnames or []
            required = list(manifest.header)
            # Optional columns may be absent, but a present one must be in its
            # declared position. No unknown or reordered column is accepted.
            expected_variants = [required + [name for i, name in enumerate(manifest.optional_columns)
                                             if mask & (1 << i)]
                                 for mask in range(1 << len(manifest.optional_columns))]
            if observed not in expected_variants:
                all_expected = set(required + list(manifest.optional_columns))
                missing = sorted(set(required) - set(observed))
                added = sorted(set(observed) - all_expected)
                raise ImportRefused(
                    f"Header mismatch in {path.name}; expected {manifest.kind} v1 exact columns; "
                    f"missing={missing}; added={added}; order_changed={not missing and not added}"
                )
            rows = list(reader)
    except (UnicodeError, csv.Error) as exc:
        raise ImportRefused(f"Cannot parse UTF-8 CSV {path.name}: {type(exc).__name__}") from exc
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ImportRefused(f"Wrong CSV column count in {path.name}")
    return rows


def prepare_source(path: Path, dataset_kind: str, manifest: IntakeManifest, *, commit: bool) -> list[dict]:
    classify_filename(path, dataset_kind, manifest)
    if commit and not manifest.verified:
        raise ImportRefused(f"Cannot --commit: {manifest.kind} schema fixture is unverified")
    return read_csv(path, manifest)
