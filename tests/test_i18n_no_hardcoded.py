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

# ─── Chieu nguoc lai: key ma code tham chieu phai ton tai o DU 6 locale ─────────

def _referenced_keys(mod) -> dict[str, str]:
    """Quet AST cua bot/ + dashboard/ lay moi literal key trong tr(...)/t(...)."""
    import ast
    out: dict[str, str] = {}
    for base in ("bot", "dashboard"):
        for py in sorted((ROOT / base).rglob("*.py")):
            if "__pycache__" in str(py):
                continue
            try:
                tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            rel = str(py.relative_to(ROOT)).replace("\\", "/")
            for n in ast.walk(tree):
                if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                        and n.func.id in ("tr", "t") and n.args):
                    continue
                args = n.args[1:] if n.func.id == "tr" else n.args[:1]
                for a in args:
                    if isinstance(a, ast.Constant) and isinstance(a.value, str):
                        k = a.value
                        if "." in k and " " not in k and k.replace("_", "").replace(".", "").isalnum():
                            out.setdefault(k, rel)
    return out


def test_every_referenced_key_exists_in_all_six_locales():
    """`tr()` roi ve TEN KEY khi key khong co trong file nao → nguoi dung thay chuoi
    "common.not_your_interaction" ngay tren Discord (da xay ra that, pre-existing).
    Test nay khop moi key trong code voi ca 6 locale; them key ma quen 1 ngon ngu
    la do ngay lap tuc."""
    import json

    refs = _referenced_keys(None)
    assert refs, "khong doc duoc key nao tu code — regex/AST hong?"
    locales = {
        lang: json.loads((ROOT / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
        for lang in ("vi", "en", "zh", "es", "pt", "fr")
    }
    missing = []
    for key, where in sorted(refs.items()):
        absent = [lang for lang, data in locales.items() if key not in data]
        if absent:
            missing.append(f"{key} (thieu {','.join(absent)}) ← {where}")
    assert not missing, (
        f"{len(missing)} key duoc code dung nhung khong co du 6 locale (nguoi dung se "
        "thay TEN KEY ngay tren Discord):"
        + "".join(f"\n  {m}" for m in missing[:25])
    )


def test_catalog_names_translate_without_leaking_keys_or_breaking_rows():
    """Ten mon an luu nguyen van tieng Viet trong DB (khong migration duoc, no la du
    lieu cua nguoi dung). `cat_name` phai: dich khi co key, giu nguyen ten khi ten la
    cua ng dung tu dat, va DAC BIET khong bao gio tra lai ten key when locale thieu dich.
    """
    import os, sys
    BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for x in (BASE, os.path.join(BASE, "bot")):
        if x not in sys.path:
            sys.path.insert(0, x)
    import cogs.economy as E
    import json

    stored = "🐟 Cá Rô Phi"
    assert stored in E._CATALOG_KEYS, "catalog khong duoc doi ten khi ma chua cap nhat"
    assert E.cat_name({"language": "en"}, stored) == "🐟 Tilapia"
    assert E.cat_name({"language": "vi"}, stored) == stored
    # ten tu dat (khong thuoc bang) → giu nguyen, khong co chuoi "economy.item_..."
    assert E.cat_name({"language": "en"}, "Tua sua cua me") == "Tua sua cua me"
    # mot key catalog phai co mat o DU 6 locale va vi == dung chuoi da luu trong DB
    vi = json.load(open(os.path.join(BASE, "locales", "vi.json"), encoding="utf-8"))
    for key in E._CATALOG_KEYS.values():
        assert key in vi, f"key {key} thieu trong vi.json"
    for lang in ("en", "zh", "es", "pt", "fr"):
        d = json.load(open(os.path.join(BASE, "locales", f"{lang}.json"), encoding="utf-8"))
        missing = [k for k in set(E._CATALOG_KEYS.values()) if k not in d]
        assert not missing, f"{lang} thieu {len(missing)} key catalog: {missing[:3]}"
