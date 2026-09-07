"""Prepare and publish dashboard files on the existing public branch."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import re
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from src.dashboard import build_dashboard
from src.dashboard.page import render


REPOSITORY = "MosesRahnama/Alts-ETL-Analytics-Project"
BRANCH = "main"
SITE = "https://mosesrahnama.github.io/Alts-ETL-Analytics-Project/"
OUTPUT = Path(tempfile.gettempdir()) / "alts-dashboard-publication"
PAYLOAD = re.compile(r'<script id="payload" type="application/json">(.*?)</script>', re.S)
NATIVE_FILES = {"records-a.csv", "records-b.csv", "records-final.csv", "pair-index.csv", "resolution.csv", "README.md"}
DATA_FOLDERS = ("data/csv", "data/extracted/tables", "data/extracted/wide", "data/extracted/fund-level")
FILE_COLUMNS = ("source", "destination", "bytes", "kind")
ASSET_PREFIX = "dashboard-data/"


def api(endpoint: str, body: dict | None = None) -> dict:
    """Use the GitHub CLI's configured repository credentials."""

    command = ["gh", "api", f"repos/{REPOSITORY}/{endpoint}"]
    if body is not None:
        command += ["--input", "-"]
        if endpoint.startswith("git/refs/"):
            command += ["--method", "PATCH"]
    result = subprocess.run(
        command, input=json.dumps(body) if body is not None else None,
        text=True, encoding="utf-8", capture_output=True, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"GitHub {endpoint}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def blob_id(content: bytes) -> str:
    return hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()


def allowed_path(value: str, completed: set[str]) -> bool:
    path = PurePosixPath(value)
    if path.is_absolute() or any(part.startswith(".") for part in path.parts) or "\\" in value:
        return False
    if value == "dashboard.html":
        return True
    if value.startswith("ledgers/working/pdf-extraction-csv/"):
        return len(path.parts) == 6 and path.parts[-2] in completed and path.name in NATIVE_FILES
    if path.suffix == ".csv":
        return value.startswith(("data/", "docs/", "costs/", "ledgers/pipeline/")) or value == "data-gathering/source_ledger.csv"
    return value.startswith("data/documents/") and path.suffix in {".pdf", ".txt"} or value in {
        "data/warehouse/extracted.duckdb", "data/warehouse/alts.duckdb", "data/warehouse/alts_mock.duckdb",
    }


def source_files(document: dict, root: Path) -> tuple[set[str], set[str]]:
    with (root / "data/extracted/review/document-summary.csv").open(encoding="utf-8-sig", newline="") as handle:
        summary = list(csv.DictReader(handle))
    completed = {row["file_id"] for row in summary}
    files = {"dashboard.html"}
    for folder in DATA_FOLDERS:
        files.update(path.relative_to(root).as_posix() for path in (root / folder).glob("*.csv"))
    for section in document["sections"]:
        for block in section["blocks"]:
            source = block.get("source", "")
            if source and allowed_path(source, completed) and (root / source).is_file():
                files.add(source)
            if section["id"] == "evidence" and block.get("source") == "data/extracted/tables/fact_observation.csv":
                for row in block.get("rows", []):
                    files.update(value for value in row if isinstance(value, str) and allowed_path(value, completed) and (root / value).is_file())
    files.update(f"data/warehouse/{name}.duckdb" for name in ("extracted", "alts", "alts_mock"))
    for value in files:
        if not allowed_path(value, completed):
            raise ValueError(f"File outside dashboard publication: {value}")
        if not (root / value).resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Source outside repository: {value}")
    return files, completed


def write_zip(target: Path, name: str, content: bytes) -> None:
    entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    entry.compress_type = zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr(entry, content)
    with zipfile.ZipFile(target) as archive:
        if archive.namelist() != [name] or archive.read(name) != content:
            raise ValueError(f"Archive differs from source: {target}")


def prepare(root: Path, output: Path) -> dict:
    """Copy the published data used by the dashboard into one upload directory."""

    output.mkdir(parents=True, exist_ok=True)
    text = (root / "dashboard.html").read_text(encoding="utf-8")
    match = PAYLOAD.search(text)
    if match is None:
        raise ValueError("Dashboard data are missing")
    document = json.loads(match.group(1))
    if document != build_dashboard.payload():
        raise ValueError("Dashboard differs from current published inputs; rebuild and test first")
    base = api(f"git/ref/heads/{BRANCH}")["object"]["sha"]
    tree = api(f"git/trees/{base}?recursive=1")
    if tree.get("truncated"):
        raise ValueError("Public repository file list is incomplete")
    remote = {item["path"]: item["sha"] for item in tree["tree"] if item["type"] == "blob"}
    files, completed = source_files(document, root)
    records = []
    downloads = {}
    for source in sorted(files - {"dashboard.html"}):
        content = (root / source).read_bytes()
        destination = ASSET_PREFIX + source
        kind = "file"
        if source.endswith(".pdf"):
            pointer = (
                "version https://git-lfs.github.com/spec/v1\n"
                f"oid sha256:{hashlib.sha256(content).hexdigest()}\nsize {len(content)}\n"
            ).encode()
            if remote.get(source) == blob_id(pointer):
                destination = f"https://media.githubusercontent.com/media/{REPOSITORY}/{base}/{source}"
                request = urllib.request.Request(destination, headers={"Range": "bytes=0-127"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    if not response.read(128).startswith(b"%PDF-"):
                        raise ValueError(f"Public PDF download is invalid: {source}")
                kind = "existing_public_pdf"
        if kind == "file":
            if source.endswith((".txt", ".duckdb", ".pdf")):
                destination += ".zip"
                kind = "zip"
            target = output / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            if kind == "zip":
                write_zip(target, Path(source).name, content)
            else:
                target.write_bytes(content)
            if target.stat().st_size >= 100_000_000:
                raise ValueError(f"File exceeds the publication size limit: {destination}")
        downloads[source] = destination
        records.append(dict(source=source, destination=destination, bytes=len(content), kind=kind))
    document["downloads"] = downloads
    for section in document["sections"]:
        for block in section["blocks"]:
            source = block.get("source", "")
            if source in downloads and downloads[source].startswith(ASSET_PREFIX):
                block["source"] = downloads[source]
                downloads[block["source"]] = block["source"]
        if section["id"] == "warehouse":
            section["blocks"].insert(0, {"kind": "note", "text": "Database and text downloads use ZIP archives containing the original file. Table search covers the displayed preview; source downloads contain every row."})
        if section["id"] == "reproduce":
            section["blocks"].insert(0, {"kind": "note", "text": "Dashboard downloads are published in dashboard-data. Repository code and its source tables retain their existing release."})
    rendered = render(document).encode("utf-8")
    (output / "dashboard.html").write_bytes(rendered)
    records.append(dict(source="dashboard.html", destination="dashboard.html", bytes=len(rendered), kind="dashboard"))
    asset_paths = {PurePosixPath(row["destination"]) for row in records if row["destination"].startswith(ASSET_PREFIX)}
    directories = {parent for path in asset_paths for parent in path.parents if str(parent).startswith(ASSET_PREFIX.rstrip("/"))}
    for directory in sorted(directories):
        children = sorted({path.parts[len(directory.parts)] for path in asset_paths if directory in path.parents})
        lines = [f"# {directory.name}", "", "| File or folder | Source |", "|---|---|"]
        for child in children:
            path = directory / child
            target = child if path in asset_paths else child + "/README.md"
            role = str(path).removeprefix(ASSET_PREFIX) if path in asset_paths else "Published dashboard files."
            lines.append(f"| `{child}` | `{role}` |" if path in asset_paths else f"| [{child}]({target}) | {role} |")
        content = ("\n".join(lines) + "\n").encode("utf-8")
        destination = str(directory / "README.md")
        (output / destination).write_bytes(content)
        records.append(dict(source=destination, destination=destination, bytes=len(content), kind="guide"))
    readme = base64.b64decode(api(f"git/blobs/{remote['README.md']}")["content"]).decode("utf-8")
    evidence_rows = next(len(block["rows"]) for section in document["sections"] if section["id"] == "evidence" for block in section["blocks"] if block.get("source", "").endswith("/fact_observation.csv"))
    notice = f"The live dashboard contains {len(completed)} extracted documents and {evidence_rows:,} evidence rows, using the files in [dashboard-data](dashboard-data/README.md). Repository code and its source tables retain their existing release."
    lines = [line for line in readme.splitlines() if not line.startswith("The live dashboard ")]
    lines = [f"[`dashboard.html`](dashboard.html) contains {len(completed)} extracted documents, {evidence_rows:,} evidence rows, database previews, quality results, performance measures, benchmark comparisons, portfolio allocations, and recorded data-completion methods. Its downloads use the separate [dashboard-data](dashboard-data/README.md) snapshot." if line.startswith("[`dashboard.html`](dashboard.html)") else line for line in lines]
    readme = lines[0] + "\n\n" + notice + "\n" + "\n".join(lines[1:]) + "\n"
    (output / "README.md").write_text(readme, encoding="utf-8", newline="")
    records.append(dict(source="README.md", destination="README.md", bytes=len(readme.encode("utf-8")), kind="public_readme"))
    with (output / "files.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FILE_COLUMNS)
        writer.writeheader()
        writer.writerows(records)
    state = dict(repository=REPOSITORY, branch=BRANCH, base=base, base_tree=tree["sha"], completed=sorted(completed), remote=remote)
    (output / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"PREPARED: {len(completed)} completed documents; {len(records)} file entries; {output}", flush=True)
    return state


def publish(output: Path) -> str:
    """Commit only prepared files, retaining the public branch's own parent."""

    state = json.loads((output / "state.json").read_text(encoding="utf-8"))
    if state["repository"] != REPOSITORY or state["branch"] != BRANCH:
        raise ValueError("Publication target changed")
    if api(f"git/ref/heads/{BRANCH}")["object"]["sha"] != state["base"]:
        raise ValueError("Public branch changed after preparation")
    with (output / "files.csv").open(encoding="utf-8", newline="") as handle:
        records = list(csv.DictReader(handle))
    changes = []
    available_blobs = set(state["remote"].values())
    for row in records:
        if row["kind"] == "existing_public_pdf":
            continue
        source = row["source"]
        destination = row["destination"]
        if row["kind"] == "guide":
            permitted = destination.startswith(ASSET_PREFIX) and destination.endswith("/README.md") and ".." not in PurePosixPath(destination).parts
        elif row["kind"] == "public_readme":
            permitted = source == destination == "README.md"
        else:
            target = source if row["kind"] == "dashboard" else ASSET_PREFIX + source + (".zip" if row["kind"] == "zip" else "")
            permitted = allowed_path(source, set(state["completed"])) and destination == target
        if not permitted:
            raise ValueError(f"Upload outside prepared scope: {destination}")
        content = (output / destination).read_bytes()
        if state["remote"].get(destination) == blob_id(content):
            continue
        before = time.monotonic()
        content_id = blob_id(content)
        blob = {"sha": content_id} if content_id in available_blobs else api("git/blobs", dict(content=base64.b64encode(content).decode("ascii"), encoding="base64"))
        if blob["sha"] != blob_id(content):
            raise ValueError(f"Uploaded file differs: {destination}")
        changes.append(dict(path=destination, mode="100644", type="blob", sha=blob["sha"]))
        available_blobs.add(blob["sha"])
        print(f"UPLOADED: {destination} ({len(content)} bytes)", flush=True)
        time.sleep(max(0, 0.85 - (time.monotonic() - before)))
    if not changes:
        print("UNCHANGED: all prepared files already match the public branch", flush=True)
        return state["base"]
    if api(f"git/ref/heads/{BRANCH}")["object"]["sha"] != state["base"]:
        raise ValueError("Public branch changed during upload; files remain unattached")
    tree = api("git/trees", dict(base_tree=state["base_tree"], tree=changes))
    commit = api("git/commits", dict(message="Update dashboard and supporting reviewer data", tree=tree["sha"], parents=[state["base"]]))
    committed_tree = api(f"git/trees/{tree['sha']}?recursive=1")
    if committed_tree.get("truncated"):
        raise ValueError("Published file comparison is incomplete")
    actual_tree = {item["path"]: item["sha"] for item in committed_tree["tree"] if item["type"] == "blob"}
    expected = {row["path"] for row in changes}
    actual = {path for path in set(actual_tree) | set(state["remote"]) if actual_tree.get(path) != state["remote"].get(path)}
    if actual != expected or any(Path(name).name == ".gitignore" for name in actual):
        raise ValueError("Public commit file set differs from prepared uploads")
    if any(path not in {"dashboard.html", "README.md"} and not path.startswith(ASSET_PREFIX) for path in actual):
        raise ValueError("Public code or source tables would change")
    api(f"git/refs/heads/{BRANCH}", dict(sha=commit["sha"], force=False))
    state.update(commit=commit["sha"], changed=sorted(expected))
    (output / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"PUBLISHED: {commit['sha']}; {len(changes)} files; public parent {state['base']}", flush=True)
    return commit["sha"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--publish", action="store_true", help="Publish the previously prepared files")
    args = parser.parse_args()
    if args.publish:
        publish(args.output)
    else:
        prepare(build_dashboard.PROJECT_ROOT, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
