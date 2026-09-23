"""Run sync() offline, answering every URL from a recorded data/sync/ snapshot.

The way to prove a change to sync.py (or fetch.py, deployments.py, charts.py)
does not alter what a sync writes. A live sync cannot prove that: upstream
answers change between two runs. This replays one run's answers instead —
the recorded body for a 200, the recorded status or error otherwise — with
max_age=0 so every request goes through the fetcher, and nothing reaches the
network.

    uv run sync-components                         # once, for a snapshot
    cp -R data/sync data/sync-snapshot
    uv run python tools/replay_sync.py data/sync-snapshot data/replay-before
    # ...make the change...
    uv run python tools/replay_sync.py data/sync-snapshot data/replay-after
    diff -r data/replay-before.normalised data/replay-after.normalised

The snapshot is only read. <output dir> gets the sync tree, and
<output dir>.normalised a copy with the timestamp keys removed from every JSON
file plus ECHO.txt, the lines the run printed — so an empty diff means the
same files, the same manifest order and the same summary.
"""

import json
import shutil
import sys
from pathlib import Path

from translator_diagram.components import load_components
from translator_diagram.sync import sync

TIMESTAMPS = {"started_at", "finished_at", "fetched_at", "checked_at"}


def replayer(snapshot: Path):
    """A Fetcher that answers from the snapshot's manifest and files."""
    manifest = json.loads((snapshot / "manifest.json").read_text())
    recorded = {f["url"]: f for f in manifest["fetches"]}

    def replay(url):
        entry = recorded.get(url)
        if entry is None:
            raise RuntimeError(f"unrecorded: {url}")
        if entry["error"]:
            raise RuntimeError(entry["error"])
        if entry["path"].startswith("root/"):
            # A root probe saved a summary, not the page; replay what it saw.
            summary = json.loads((snapshot / entry["path"]).read_text())
            return summary["status"], b"", summary["content_type"]
        if entry["status"] == 200 and (snapshot / entry["path"]).exists():
            return 200, (snapshot / entry["path"]).read_bytes()
        return entry["status"], b""

    return replay


def strip(node):
    if isinstance(node, dict):
        return {k: strip(v) for k, v in node.items() if k not in TIMESTAMPS}
    if isinstance(node, list):
        return [strip(v) for v in node]
    return node


def normalise(out: Path, lines: list[str]) -> Path:
    normalised = Path(f"{out}.normalised")
    shutil.rmtree(normalised, ignore_errors=True)
    for path in out.rglob("*"):
        if path.is_dir():
            continue
        target = normalised / path.relative_to(out)
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".json":
            try:
                body = strip(json.loads(path.read_text()))
                target.write_text(json.dumps(body, indent=1))
                continue
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        shutil.copyfile(path, target)
    (normalised / "ECHO.txt").write_text("\n".join(lines) + "\n")
    return normalised


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("usage: replay_sync.py <snapshot dir> <output dir>")
    snapshot, out = Path(sys.argv[1]), Path(sys.argv[2])
    shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(snapshot, out)
    lines: list[str] = []
    sync(load_components(Path("components")), out, fetcher=replayer(snapshot),
         max_age=0, echo=lines.append)
    print(f"{len(lines)} lines echoed; compare {normalise(out, lines)}")


if __name__ == "__main__":
    main()
