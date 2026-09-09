#!/usr/bin/env python3
"""Import Telegram channel export (export/result.json) into Hugo posts.

Re-run safe: keeps track of already-imported message ids in
scripts/.import-state.json, so re-running after a new Telegram export
(which repeats old messages and adds new ones) only creates posts for
new messages.

Usage:
    python3 scripts/import_telegram.py [--export DIR] [--dry-run]
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = Path(__file__).resolve().parent / ".import-state.json"

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def transliterate(text: str) -> str:
    out = []
    for ch in text.lower():
        if ch in TRANSLIT:
            out.append(TRANSLIT[ch])
        elif ch.isalnum():
            out.append(ch)
        else:
            out.append(" ")
    return "".join(out)


def slugify(text: str, max_words: int = 6) -> str:
    translit = transliterate(text)
    words = [w for w in re.split(r"\s+", translit) if w]
    slug = "-".join(words[:max_words])
    return slug or "post"


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"imported_ids": []}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def extract_text(message: dict) -> str:
    entities = message.get("text_entities") or []
    if entities:
        return "".join(e.get("text", "") for e in entities)
    text = message.get("text", "")
    return text if isinstance(text, str) else ""


def group_messages(messages: list) -> list:
    """Group consecutive `message`-type entries sharing the same timestamp
    (Telegram exports albums as separate messages with identical `date`)."""
    groups = []
    current = None
    for m in messages:
        if m.get("type") != "message":
            continue
        if current is not None and current[0]["date"] == m["date"]:
            current.append(m)
        else:
            current = [m]
            groups.append(current)
    return groups


def build_post(group: list, export_dir: Path, uploads_dir: Path, dry_run: bool):
    first = group[0]
    texts = [extract_text(m).strip() for m in group]
    text = "\n\n".join(t for t in texts if t)

    photos = []
    for m in group:
        photo_rel = m.get("photo")
        if not photo_rel:
            continue
        src = export_dir / photo_rel
        dest_name = Path(photo_rel).name
        dest = uploads_dir / dest_name
        if not dry_run and src.exists() and not dest.exists():
            shutil.copy2(src, dest)
        photos.append(dest_name)

    date = first["date"]
    ids = [m["id"] for m in group]

    if text:
        title_line = text.splitlines()[0].strip()
        title = title_line[:70].rstrip()
        if len(title_line) > 70:
            title += "…"
    elif photos:
        title = f"Фото {date[:10]}"
    else:
        title = f"Запись {date[:10]}"

    slug_source = title if text else date[:10]
    filename = f"{date[:10]}-{slugify(slug_source)}-{ids[0]}.md"

    lines = ["---"]
    lines.append(f'title: "{title.replace(chr(34), chr(39))}"')
    lines.append(f"date: {date}")
    lines.append("draft: false")
    if photos:
        lines.append("cover:")
        lines.append(f"    image: /uploads/{photos[0]}")
    lines.append("---")
    lines.append("")
    if text:
        lines.append(text)
        lines.append("")
    for p in photos:
        lines.append(f"![]({'/uploads/' + p})")
        lines.append("")

    content = "\n".join(lines).rstrip() + "\n"
    return filename, content, ids


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", default=str(ROOT / "export"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    export_dir = Path(args.export)
    result_json = export_dir / "result.json"
    if not result_json.exists():
        sys.exit(f"Не найден {result_json}")

    data = json.loads(result_json.read_text())
    messages = data.get("messages", [])
    groups = group_messages(messages)

    state = load_state()
    imported = set(state.get("imported_ids", []))

    posts_dir = ROOT / "content" / "posts"
    uploads_dir = ROOT / "static" / "uploads"
    posts_dir.mkdir(parents=True, exist_ok=True)
    uploads_dir.mkdir(parents=True, exist_ok=True)

    created = 0
    for group in groups:
        ids = [m["id"] for m in group]
        if any(i in imported for i in ids):
            continue

        filename, content, ids = build_post(group, export_dir, uploads_dir, args.dry_run)
        dest = posts_dir / filename
        print(f"+ {dest.relative_to(ROOT)}")
        if not args.dry_run:
            dest.write_text(content)
        imported.update(ids)
        created += 1

    if not args.dry_run:
        state["imported_ids"] = sorted(imported)
        save_state(state)

    print(f"\nГотово: {created} новых постов.")


if __name__ == "__main__":
    main()
