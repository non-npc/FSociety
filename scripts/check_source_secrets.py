from __future__ import annotations

import re
import sys
from pathlib import Path


CLIENT_ROOT = Path(__file__).resolve().parents[1]
SKIPPED_PARTS = {".git", "__pycache__", "build", "data", "dist", "pyinstaller-dist"}
TEXT_SUFFIXES = {
    ".bat",
    ".desktop",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yml",
    ".yaml",
}

# Split sensitive prefixes so this guard does not match its own source.
RULES = {
    "Nostr private recovery key": re.compile("nse" + r"c1[023456789acdefghjklmnpqrstuvwxyz]{40,}"),
    "encrypted Nostr vault record": re.compile(
        "ncrypt" + r"sec1[023456789acdefghjklmnpqrstuvwxyz]{40,}"
    ),
    "PEM private key": re.compile("BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    "Windows developer path": re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+\\"),
    "Linux/macOS developer path": re.compile(r"/(?:home|Users)/[^/\s]+/"),
}


def main() -> int:
    findings: list[str] = []
    for path in CLIENT_ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIPPED_PARTS for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in RULES.items():
            if pattern.search(text):
                findings.append(f"{path.relative_to(CLIENT_ROOT)}: {label}")
    if findings:
        print("SECURITY CHECK FAILED: sensitive source material may be present.")
        for finding in findings:
            print(f"  {finding}")
        return 1
    print("Source secret check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
