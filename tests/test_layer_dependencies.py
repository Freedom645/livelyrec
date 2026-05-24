"""層間依存方向のテスト。

詳細: docs/design/06_詳細設計_アーキテクチャ.md §2

- domain は他層に依存しない
- infrastructure は application/ui に依存しない
- application は ui に依存しない
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "livelyrec"

_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+(livelyrec[\w\.]*)", re.MULTILINE)


def _imports_in(layer: str) -> set[tuple[Path, str]]:
    layer_dir = PKG / layer
    found: set[tuple[Path, str]] = set()
    if not layer_dir.exists():
        return found
    for py in layer_dir.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for m in _IMPORT_RE.finditer(text):
            found.add((py, m.group(1)))
    return found


def _violations(layer: str, forbidden_prefixes: tuple[str, ...]) -> list[str]:
    return [
        f"{path.relative_to(ROOT)}: imports {mod}"
        for path, mod in _imports_in(layer)
        if any(mod == p or mod.startswith(p + ".") for p in forbidden_prefixes)
    ]


def test_domain_does_not_depend_on_other_layers() -> None:
    violations = _violations(
        "domain",
        ("livelyrec.application", "livelyrec.infrastructure", "livelyrec.ui"),
    )
    assert not violations, "domain layer must not depend on other layers:\n" + "\n".join(violations)


def test_infrastructure_does_not_depend_on_application_or_ui() -> None:
    violations = _violations(
        "infrastructure",
        ("livelyrec.application", "livelyrec.ui"),
    )
    assert not violations, "infrastructure layer must not depend on application/ui:\n" + "\n".join(violations)


def test_application_does_not_depend_on_ui() -> None:
    violations = _violations("application", ("livelyrec.ui",))
    assert not violations, "application layer must not depend on ui:\n" + "\n".join(violations)


def test_shared_does_not_depend_on_other_layers() -> None:
    violations = _violations(
        "shared",
        ("livelyrec.domain", "livelyrec.application", "livelyrec.infrastructure", "livelyrec.ui"),
    )
    assert not violations, "shared layer must not depend on other layers:\n" + "\n".join(violations)
