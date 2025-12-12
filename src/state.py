import json
from pathlib import Path
from typing import Any, Dict, Set


def load_downloaded_arnumbers(state_file: Path) -> Set[str]:
    if not state_file.exists():
        return set()

    downloaded: Set[str] = set()
    for line in state_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue

        if record.get("status") == "downloaded" and record.get("arnumber"):
            downloaded.add(str(record["arnumber"]))

    return downloaded


def append_state_record(state_file: Path, record: Dict[str, Any]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with state_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
