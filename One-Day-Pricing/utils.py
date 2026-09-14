"""Local file, date, hash, and deterministic-ID helpers for One-Day Pricing."""
from __future__ import annotations
import csv
import hashlib
import json
import subprocess
from calendar import monthrange
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

class DataError(RuntimeError):
    """Raised when an input or persisted contract is invalid."""

def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise DataError(f'missing CSV: {path}')
    with path.open('r', encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))

def iter_csv(path: Path):
    if not path.is_file():
        raise DataError(f'missing CSV: {path}')
    handle = path.open('r', encoding='utf-8-sig', newline='')
    try:
        for row in csv.DictReader(handle):
            yield row
    finally:
        handle.close()

def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str] | None=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else []
    temp = path.with_name(path.name + '.part')
    with temp.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), lineterminator='\n', extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(path)

def read_json(path: Path) -> Any:
    if not path.is_file():
        raise DataError(f'missing JSON: {path}')
    return json.loads(path.read_text(encoding='utf-8-sig'))

def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.part')
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    temp.replace(path)

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()

def hash_json(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def stable_id(prefix: str, *parts: object, length: int=20) -> str:
    body = '|'.join((str(part) for part in parts))
    digest = hashlib.sha256(body.encode('utf-8')).hexdigest()[:length].upper()
    return f'{prefix}_{digest}'

def parse_date(value: object, field: str='date') -> date:
    text = str(value or '').strip()
    if not text:
        raise DataError(f'{field} is blank')
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise DataError(f'invalid {field}: {text}') from exc

def optional_date(value: object) -> date | None:
    text = str(value or '').strip()
    return date.fromisoformat(text) if text else None

def number(value: object, field: str='number') -> float:
    text = '' if value is None else str(value).strip().replace(',', '')
    if not text:
        raise DataError(f'{field} is blank')
    try:
        result = float(text)
    except ValueError as exc:
        raise DataError(f'invalid {field}: {value}') from exc
    if result != result or result in (float('inf'), float('-inf')):
        raise DataError(f'non-finite {field}: {value}')
    return result

def optional_number(value: object) -> float | None:
    text = '' if value is None else str(value).strip().replace(',', '')
    return None if not text else float(text)

def fmt(value: float | None, digits: int=10) -> str:
    return '' if value is None else f'{value:.{digits}f}'

def add_months(day: date, months: int) -> date:
    total = day.year * 12 + (day.month - 1) + months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))

def git_state(root: Path) -> dict[str, Any]:

    def run(*args: str) -> str:
        completed = subprocess.run(['git', *args], cwd=root, text=True, capture_output=True, encoding='utf-8', check=True)
        return completed.stdout.strip()
    try:
        return {'commit': run('rev-parse', 'HEAD'), 'branch': run('rev-parse', '--abbrev-ref', 'HEAD'), 'dirty': bool(run('status', '--porcelain'))}
    except (OSError, subprocess.SubprocessError):
        return {'commit': '', 'branch': '', 'dirty': None}

def fingerprint(paths: Iterable[Path], root: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted({p.resolve() for p in paths}, key=lambda p: str(p).casefold()):
        if not path.is_file():
            raise DataError(f'fingerprint input is missing: {path}')
        try:
            rel = path.relative_to(root.resolve()).as_posix()
        except ValueError:
            rel = str(path)
        records.append({'path': rel, 'bytes': path.stat().st_size, 'sha256': sha256_file(path)})
    return records

def verify_fingerprints(records: Sequence[Mapping[str, Any]], root: Path) -> list[str]:
    errors: list[str] = []
    for record in records:
        path = root / str(record['path'])
        if not path.is_file():
            errors.append(f'missing input: {record['path']}')
            continue
        if path.stat().st_size != int(record['bytes']):
            errors.append(f'size changed: {record['path']}')
            continue
        if sha256_file(path) != record['sha256']:
            errors.append(f'hash changed: {record['path']}')
    return errors

def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
