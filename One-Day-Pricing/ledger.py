"""Update the static implementation status table."""
from __future__ import annotations
import csv
from pathlib import Path
HERE = Path(__file__).resolve().parent
PATH = HERE / 'IMPLEMENTATION.csv'

def update(stage: str, status: str, note: str='') -> None:
    with PATH.open('r', encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0].keys()) if rows else ['stage', 'status', 'depends_on', 'artifacts', 'acceptance', 'notes']
    found = False
    for row in rows:
        if row['stage'] == stage:
            row['status'] = status
            if note:
                row['notes'] = note
            found = True
    if not found:
        raise ValueError(f'unknown implementation stage: {stage}')
    temp = PATH.with_name(PATH.name + '.part')
    with temp.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator='\n')
        w.writeheader()
        w.writerows(rows)
    temp.replace(PATH)
