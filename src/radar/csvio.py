"""Strict CSV reading into pydantic rows, with every error reported at once."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

M = TypeVar("M", bound=BaseModel)


class DataError(Exception):
    """One or more input files are invalid. `problems` lists each one."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


def read_rows(path: Path, model: type[M]) -> list[M]:
    rows: list[M] = []
    problems: list[str] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {n for n, fi in model.model_fields.items() if fi.is_required()}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise DataError([f"{path}: missing columns {sorted(missing)}"])
        for line, raw in enumerate(reader, start=2):
            data = {k: v for k, v in raw.items() if k is not None and v is not None and v.strip() != ""}
            try:
                rows.append(model.model_validate(data))
            except ValidationError as e:
                for err in e.errors():
                    loc = ".".join(str(x) for x in err["loc"])
                    problems.append(f"{path.name}:{line} {loc}: {err['msg']}")
    if problems:
        raise DataError(problems)
    return rows


def write_rows(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in columns})


def read_dicts(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))
