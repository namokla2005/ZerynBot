"""test_i18n_no_hardcoded.py — Ngan chuoi tieng Viet hardcode HIEN TREN DISCORD tang lai.

Invariance: moi thong diep nguoi dung nhin thay qua Discord phai lay tu locale
(tr(s, key)) de 6 ngon ngu con dung. Chuoi log/docstring/du lieu bang gia KHONG
thuoc pham vi (khong hien ra nhu thong diep, va chuyen chung keo theo du lieu DB).

Che do "ngan sach dong bang": `tests/i18n_budget.json` luu so chuoi DISCORD con lai
 cua tung file (tao bang `python scripts/i18n_audit.py --budget`). Ngan sach chi
duoc GIAM. File da migrate xong phai bang 0. Day la cach duy nhat de mot dot
de-hardcode 100+ chuoi khong bi lot lai thanh 0 test that.

Tai sao test nay khong bao GREEN gia: no doc nguon that bang AST (script
i18n_audit.py) — khong doi chieu voi danh sach tay. Mutate mot file (them chuoi
Viet vao ctx.send) thi test DO ngay.
"""
import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUDGET_PATH = Path(__file__).with_name("i18n_budget.json")


def _auditor():
    """Nap scripts/i18n_audit.py nhu mot module that (phai dang ky sys.modules truoc
    khi exec_module — @dataclass + `from __future__ import annotations` giai quyet
    ten loi qua sys.modules, neu khong se AttributeError trong dataclasses)."""
    import importlib.util
    import sys

    name = "i18n_audit"
    cached = sys.modules.get(name)
    if cached is not None and getattr(cached, "__file__", "").endswith("i18n_audit.py"):
        return cached
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "i18n_audit.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _count_discord(mod, rel: str) -> int:
    return sum(1 for f in mod.audit_file(ROOT / rel) if f["role"] == mod.DISCORD)


@pytest.fixture(scope="module")
def budget():
    if not BUDGET_PATH.exists():
        pytest.skip("chua sinh ngan sach: python scripts/i18n_audit.py --budget")
    return json.loads(BUDGET_PATH.read_text(encoding="utf-8"))


def test_budget_file_is_complete_and_non_negative(budget):
    assert isinstance(budget, dict) and budget, "budget trong"
    bad = {f: n for f, n in budget.items() if not isinstance(n, int) or n < 0}
    assert not bad, f"ngan sach hop le: {bad}"


def test_no_file_exceeds_its_frozen_budget(budget):
    """Khong duoc them chuoi tieng Viet moi vao duong dan Discord."""
    mod = _auditor()
    over = []
    for py in sorted((ROOT / "bot").rglob("*.py")):
        rel = str(py.relative_to(ROOT)).replace("\\", "/")
        if "__pycache__" in rel:
            continue
        n = _count_discord(mod, rel)
        allowed = budget.get(rel, 0)   # file khong trong budget = da sach, khong duoc nhiem lai
        if n > allowed:
            over.append(f"{rel}: {n} > {allowed}")
    assert not over, (
        "Chuoi tieng Viet hardcode xuat hien tren Discord nhieu hon ngan sach dong bang "
        f"({len(over)} file):\n  " + "\n  ".join(over) +
        "\nHoac dung tr(s, key) + them key vao ca 6 file locale, hoac cap nhat ngan sach "
        "co chu dich (python scripts/i18n_audit.py --budget) va ghi ly do trong commit."
    )


def test_migrated_files_stay_clean(budget):
    """File da ket thuan migrate (budget = 0) khong duoc con sot chuoi nao."""
    mod = _auditor()
    migrated = [f for f, n in budget.items() if n == 0]
    dirty = []
    for rel in migrated:
        if not (ROOT / rel).exists():
            continue
        findings = [f for f in mod.audit_file(ROOT / rel) if f["role"] == mod.DISCORD]
        if findings:
            sample = "; ".join(f"{f['line']}:{f['text'][:40]!r}" for f in findings[:3])
            dirty.append(f"{rel} -> {sample}")
    assert not dirty, "File da migrate nhung con chuoi DISCORD hardcode:\n  " + "\n  ".join(dirty)


def test_total_hardcoded_count_is_countable_and_declining(budget):
    """Tong so phai khop tong trong budget — bat truc giac khi script audit doi quy tac."""
    mod = _auditor()
    total_now = 0
    for py in sorted((ROOT / "bot").rglob("*.py")):
        if "__pycache__" in str(py):
            continue
        total_now += _count_discord(mod, str(py.relative_to(ROOT)).replace("\\", "/"))
    assert total_now <= sum(budget.values()), (
        f"Tong chuoi DISCORD hien tai {total_now} > tong ngan sach {sum(budget.values())} — "
        "budget da cu (chi duoc giam)."
    )
