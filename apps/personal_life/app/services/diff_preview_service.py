from __future__ import annotations

import difflib
from typing import Any


def build_diff_preview(original: str, generated: str, file_path: str) -> str:
    original_lines = original.splitlines()
    generated_lines = generated.splitlines()
    diff_lines = list(
        difflib.unified_diff(
            original_lines,
            generated_lines,
            fromfile=f"{file_path} (current)",
            tofile=f"{file_path} (preview)",
            lineterm="",
        )
    )
    if not diff_lines:
        return "No changes."
    return "\n".join(diff_lines)


def summarize_diff(original: str, generated: str) -> dict[str, Any]:
    added = 0
    removed = 0
    sections = 0
    for line in difflib.unified_diff(original.splitlines(), generated.splitlines(), lineterm=""):
        if line.startswith("@@"):
            sections += 1
        elif line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return {
        "added_lines": added,
        "removed_lines": removed,
        "changed_sections": sections,
    }
