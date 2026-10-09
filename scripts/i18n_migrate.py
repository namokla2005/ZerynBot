"""i18n_migrate.py — Cuoi ngon chuoi tieng Viet hardcode (role DISCORD) sang tr(key).

Vong lap:
    python scripts/i18n_migrate.py plan  bot/cogs/verify.py
    python scripts/i18n_migrate.py apply bot/cogs/verify.py --dry-run
    python scripts/i18n_migrate.py apply bot/cogs/verify.py --translations tr.json

Thiet ke (va ly do tu choi lam tieu):
  * Chi cham vao chuoi role DISCORD theo `i18n_audit.py`. Log, docstring, bang gia
    (CATALOG — ten item da nam trong DB) va chuoi ben trong kwargs cua `tr()` duoc
    GIU NGUYEN va bao ra de nguoi quyet.
  * cung text → cung mot key (verify.py lap lai cung mot canh bao 35 lan → 1 key).
  * Placeholder giu ten goi duoc tu bieu thuc va GIU NGUYÊN format-spec (`{amount:,}`)
    vi validate_i18n.py doi chieu placeholder giua 6 ngon ngu.
  * vi.json duoc nap bang chinh text trong source → khong the lech tho quen.
  * KHONG tu chen `await async_get_guild_settings()` vao giua ham, KHONG tu them
    import `tr`: hai viec nay doi hieu scope cua tung lenh, de tay nguoi lam va
    bao trong danh sach manual.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from i18n_audit import DISCORD, audit_file  # noqa: E402

LOCALES_DIR = ROOT / "locales"
LANGS = ["vi", "en", "zh", "es", "pt", "fr"]
SETTINGS_VARS = ("gs", "s", "settings", "guild_settings")
# Bien nào "mang ngon ngu"? chi guild_settings moi co khoa `language`; cac
# async_get_<module>_settings KHONG co → dung no trong tr() khien server en/zh/es
# mãi hiện tiếng Việt (lou pre-existing trong verify.py/birthday.py).
GUILD_SETTINGS_HINT = "get_guild_settings"
GUILD_EXPRS = (
    ("ctx", "ctx.guild", "str(ctx.guild.id)"),
    ("interaction", "interaction.guild", "str(interaction.guild.id)"),
    ("self", "self.guild", "str(self.guild.id)"),
    ("guild", "guild", "str(guild.id)"),
    ("guild_id", "guild_id", "guild_id"),
)
GLOSSARY_PATH = Path(__file__).resolve().parent / "i18n_glossary.json"
PH_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(?::[^}]*)?\}")

MODULE_PREFIX = {
    "player": "music", "views": "music", "cog_voice": "music", "extractor": "music",
    "embeds": "music",
}


def slugify(text: str, max_words: int = 5) -> str:
    """'Bạn phải liên kết Discord trước!' → 'ban_phai_lien_ket_discord_truoc'.

    'Đ'/'đ' khong bi NFD tach thanh D + mark → phai thay thu cong, neu khong key mat
    chu dau ('Đã xảy ra' → 'a_xay_ra').
    """
    pre = text.replace("Đ", "D").replace("đ", "d")
    ascii_txt = unicodedata.normalize("NFD", pre).encode("ascii", "ignore").decode()
    words = [w.lower() for w in re.findall(r"[A-Za-z0-9_]+", ascii_txt) if not w.isdigit()][:max_words]
    return "_".join(w.strip("_") for w in words if w.strip("_")) or "msg"


def placeholder_name(expr_src: str, idx: int) -> str:
    tail = re.sub(r"\(.*$", "", expr_src).split(".")[-1]
    tail = re.sub(r"[^0-9a-zA-Z_]", "", tail).lower().lstrip("_")
    if re.fullmatch(r"[a-z_][a-z0-9_]{0,24}", tail or "") and tail not in {"self", "id", "str", "int", "format"}:
        return tail
    return f"p{idx}"


def _offset(src: str, lineno: int, col: int) -> int:
    """AST col_offset/end_col_offset la BYTE UTF-8 trong dong, KHONG phai ky tu.

    Voi tieng Viet ('ạ' = 3 byte) nen quy doi tho la an 3-5 ky tu vuot qua doi tuong,
    splice theo to do do se xoa nham dau phay/xuong dong lam hu file. Doi ra chi so
    ky tu bang cach cat byte roi decode.
    """
    lines = src.splitlines(keepends=True)
    prefix = sum(len(l) for l in lines[: lineno - 1])
    line = lines[lineno - 1] if lineno - 1 < len(lines) else ""
    raw = line.encode("utf-8")
    char_col = len(raw[:col].decode("utf-8", "ignore"))
    return prefix + min(char_col, len(line))


def build_template(node) -> tuple[str, list[tuple[str, str]]] | None:
    """(template_vi, [(ten_placeholder, bieu_thuc_source)]) hoac None = can tay."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.replace("{", "{{").replace("}", "}}"), []
    if not isinstance(node, ast.JoinedStr):
        return None
    parts, kwargs = [], []
    for i, val in enumerate(node.values):
        if isinstance(val, ast.Constant) and isinstance(val.value, str):
            parts.append(val.value.replace("{", "{{").replace("}", "}}"))
        elif isinstance(val, ast.FormattedValue):
            expr = ast.unparse(val.value)
            if "await " in expr or ":=" in expr:
                return None
            name = placeholder_name(expr, i)
            while any(n == name for n, _ in kwargs):
                name += "_x"
            spec = ""
            if val.conversion and val.conversion != -1:   # Python >= 3.8: -1 = khong co conversion
                spec += "!" + chr(val.conversion)
            if val.format_spec is not None:
                vs = getattr(val.format_spec, "values", [])
                if any(isinstance(v, ast.FormattedValue) for v in vs):
                    return None      # spec động → để tay
                spec += ":" + "".join(v.value for v in vs if isinstance(v, ast.Constant))
            parts.append("{" + name + spec + "}")
            kwargs.append((name, expr))
        else:
            return None
    return "".join(parts), kwargs


def _callee_of(node) -> str:
    """Ten ham duoc goi o ve phai cua phep gan (go bo `await` va `X if guard else None`)."""
    while isinstance(node, ast.Await):
        node = node.value
    if isinstance(node, ast.IfExp):        # gs = await get(...) if ctx.guild else None
        node = node.body
        while isinstance(node, ast.Await):
            node = node.value
    if isinstance(node, ast.Call):
        return ast.unparse(node.func)
    if node is None:
        return "None"
    return type(node).__name__


def function_scopes(path: Path) -> dict[int, dict]:
    """line → info function gan nhat chua line do (co bien settings khong, async khong).

    `assigned` luu DONG gan bien LAN DAU va `except_ranges` luu pham vi tung `except:`
    — ca hai can thiet: `s = await ...` o trong try ma chuoi lai nam TRONG except phia
    duoi thi `s` chua chac da ton tai tai dong do (tr(s, ...) o day là NameError mà
    pytest khong phat hien vi duong dan do roi vao exception).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[int, dict] = {}

    def visit(node, is_async: bool):
        params = set()
        for grp in (node.args.posonlyargs, node.args.args, node.args.kwonlyargs,
                    [node.args.vararg, node.args.kwarg]):
            for x in grp or []:
                if getattr(x, "arg", None):
                    params.add(x.arg)
        assigned: dict[str, tuple[int, str]] = {}

        def bind(name: str, lineno: int, callee: str):
            prev = assigned.get(name)
            if prev is None or lineno < prev[0]:
                assigned[name] = (lineno, callee)

        for a in ast.walk(node):
            if isinstance(a, ast.Assign):
                callee = _callee_of(a.value)
                for t in a.targets:
                    if isinstance(t, ast.Name):
                        bind(t.id, a.lineno, callee)
            elif isinstance(a, (ast.AnnAssign, ast.AugAssign)) and isinstance(a.target, ast.Name):
                bind(a.target.id, a.lineno, _callee_of(a.value) if a.value else "None")
            elif isinstance(a, (ast.Import, ast.ImportFrom)):
                for al in a.names:
                    bind((al.asname or al.name).split(".")[0], a.lineno, "import")
            elif isinstance(a, ast.ExceptHandler) and a.name:
                bind(a.name, a.lineno, "except")
            elif isinstance(a, (ast.For, ast.AsyncFor)) and isinstance(a.target, ast.Name):
                bind(a.target.id, a.lineno, "for")
            elif isinstance(a, ast.With) or isinstance(a, ast.AsyncWith):
                for item in a.items:
                    if isinstance(item.optional_vars, ast.Name):
                        bind(item.optional_vars.id, a.lineno, "with")

        except_ranges = []
        for a in ast.walk(node):
            if isinstance(a, ast.Try):
                for h in a.handlers:
                    except_ranges.append((h.lineno, h.end_lineno or h.lineno))
        info = {
            "name": node.name, "params": params, "assigned": assigned,
            "is_async": is_async, "except_ranges": except_ranges, "node": node,
        }
        for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
            out.setdefault(line, info)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, isinstance(child, ast.AsyncFunctionDef))

    def walk(body):
        for st in body:
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(st, isinstance(st, ast.AsyncFunctionDef))
            elif isinstance(st, ast.ClassDef):
                walk(st.body)

    walk(tree.body)
    return out


def module_has_tr(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for st in tree.body:
        if isinstance(st, ast.ImportFrom) and any(al.name == "tr" for al in st.names):
            return True
        if isinstance(st, ast.Import):
            for al in st.names:
                if al.name.split(".")[-1] == "tr" or (al.asname or "") == "tr":
                    return True
    return False


class Plan:
    def __init__(self, rel: str):
        self.rel = rel
        self.edits: list[dict] = []
        self.keys: dict[str, tuple[str, list]] = {}
        self.text_to_key: dict[str, str] = {}
        self.manual: list[dict] = []
        self.deferred: list[dict] = []


def read_raw(path: Path) -> str:
    """Doc giu NGUYÊN line ending (repo nay la CRLF trong worktree — neu doi sang LF
    thi whole-file diff che mat hoan toan thay doi that can review)."""
    return open(path, encoding="utf-8", newline="").read()


def write_raw(path: Path, text: str):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def dominant_newline(text: str) -> str:
    return "\r\n" if text.count("\r\n") > text.count("\n") - text.count("\r\n") else "\n"


def guild_source_of(info_names: set[str]) -> tuple[str, str] | None:
    """Chon bieu thuc guild id an toat nhat ham dang dung."""
    for param, guard, gid in GUILD_EXPRS:
        if param in info_names:
            return guard, gid
    return None


def plan_fetches(rel: str) -> list[dict]:
    """GIAI DOAN 1: chen `gs = await async_get_guild_settings(...)` vao dau ham which
    can ngon ngu server ma chua co bien nao mang `language`.

    Tam phan hai buoc (fetch truoc, splice sau) vi chen dong lam so dong dich chuyen,
    con splice theo toa do ky tu thi khong. Moi buoc duoc py_compile rieng.
    """
    path = ROOT / rel
    src = read_raw(path)
    tree = ast.parse(src)
    if not module_has_guild_helper(path):
        return []
    findings = [f for f in audit_file(path) if f["role"] == DISCORD]
    scopes = function_scopes(path)
    per_func: dict[int, dict] = {}
    for f in findings:
        if "(f-expr)" in f["why"] or f["why"].startswith("tr:"):
            continue
        info = scopes.get(f["line"])
        if not info or not info["is_async"]:
            continue
        if pick_var(info, f["line"]):
            continue
        key = id(info)
        if key in per_func:
            continue
        names = set(info["params"]) | set(info["assigned"])
        gs = guild_source_of(names)
        if not gs:
            continue
        per_func[key] = {"info": info, "guard": gs[0], "gid": gs[1], "name": info["name"]}

    inserts = []
    lines = src.splitlines(keepends=True)
    for item in per_func.values():
        info = item["info"]
        node = info["node"]
        first = node.body[0]
        is_doc = (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                  and isinstance(first.value.value, str))
        # FunctionDef.lineno tro chi DECORATOR dau tien, khong phai dong `def` →
        # tinh theo statement dau tien cua body: chen TRUOC no (hoac SAU docstring).
        at_index = first.end_lineno if is_doc else first.lineno - 1
        inserts.append({"at_index": at_index, "name": item["name"],
                        "code": f"gs = await async_get_guild_settings({item['gid']}) if {item['guard']} else None"})
    return inserts


def module_has_guild_helper(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for st in tree.body:
        if isinstance(st, ast.ImportFrom) and any(al.name == "async_get_guild_settings" for al in st.names):
            return True
    return False


def pick_var(info: dict, lineno: int) -> str | None:
    """Bien settings dang dung o dong `lineno`: phai mang ngon ngu server.

    Trong `except:` van dung duoc NEU phep gan xay ra TUOC nhan xu ly do
    (`gs = ...` o dau ham, roi moi co try/except) — day la dang pho bien sau giai
    doan `fetch`. Nguoc lai (`s` gan ben trong try roi loi sang except) thi `s`
    chua ton tai, dung la NameError.
    """
    for cand in SETTINGS_VARS:
        if cand in info["params"]:
            return cand
        rec = info["assigned"].get(cand)
        if not rec:
            continue
        first_line, callee = rec
        if GUILD_SETTINGS_HINT not in callee or first_line > lineno:
            continue
        enclosing = [a for a, b in info["except_ranges"] if a <= lineno <= b]
        if enclosing and first_line > min(enclosing):
            continue          # gan ben trong chinh handler → chua chac da ton tai
        return cand
    return None


def in_except(info: dict, lineno: int) -> bool:
    return any(a <= lineno <= b for a, b in info["except_ranges"])


def apply_fetches(rel: str, inserts: list[dict]) -> int:
    path = ROOT / rel
    src = read_raw(path)
    lines = src.splitlines(keepends=True)
    nl = "\r\n" if "\r\n" in src else "\n"
    for ins in sorted(inserts, key=lambda x: -x["at_index"]):
        idx = ins["at_index"]
        indent = re.match(r"[ \t]*", lines[idx]).group(0) if idx < len(lines) else "        "
        lines.insert(idx, f"{indent}{ins['code']}{nl}")
    out = "".join(lines)
    ast.parse(out)
    write_raw(path, out)
    return len(inserts)


def plan_file(rel: str, prefix: str | None = None) -> Plan:
    path = ROOT / rel
    plan = Plan(rel)
    src = read_raw(path)
    tree = ast.parse(src)
    findings = [f for f in audit_file(path) if f["role"] == DISCORD]
    if not findings:
        return plan
    if not module_has_tr(path):
        plan.manual.append({"line": 0, "reason": "module CHUA import tr — them thu cong", "text": ""})
    scopes = function_scopes(path)

    nodes: dict[tuple[int, int], ast.AST] = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.Constant, ast.JoinedStr)):
            nodes[(getattr(n, "lineno", 0), getattr(n, "col_offset", -1))] = n

    stem = path.name.replace(".py", "")
    key_prefix = prefix or MODULE_PREFIX.get(stem, stem)
    used: set[str] = set()

    for f in sorted(findings, key=lambda x: (x["line"], x["col"])):
        text = f["text"]
        if f["why"].startswith("tr:"):
            plan.deferred.append({**f, "reason": "nam trong kwargs cua tr() — quyet rieng"})
            continue
        if "(f-expr)" in f["why"]:
            plan.deferred.append({**f, "reason": "chuoi nam TRONG bieu thuc cua f-string "
                                                 "(ternary/nia) — can tach key rieng bang tay"})
            continue
        node = nodes.get((f["line"], f["col"]))
        if node is None:
            plan.manual.append({**f, "reason": "khong tim thay node theo toa do"})
            continue

        if text in plan.text_to_key:
            key = plan.text_to_key[text]
        else:
            built = build_template(node)
            if built is None:
                plan.manual.append({**f, "reason": "placeholder phuc tap (await/walrus/spec dong)"})
                continue
            base = f"{key_prefix}.{slugify(text)}"
            key, n = base, 2
            while key in used:
                key, n = f"{base}_{n}", n + 1
            used.add(key)
            plan.text_to_key[text] = key
            plan.keys[key] = built

        info = scopes.get(f["line"])
        if info is None:
            plan.manual.append({**f, "reason": "module level/class body — can tay xu ly"})
            continue
        sv = pick_var(info, f["line"])
        if sv is None:
            has_any = any(v in info["assigned"] or v in info["params"] for v in SETTINGS_VARS)
            detail = (f"{info['name']}(): {', '.join(sorted(v for v in SETTINGS_VARS if v in info['assigned'] or info['params']))}"
                      f" duoc gan tu {info['assigned'].get('s', ('', '?'))[1] if 's' in info['assigned'] else '?'}"
                      if has_any else f"{info['name']}(): chua co bien settings")
            plan.manual.append({**f, "reason": detail + " — chay lenh `fetch` truoc"})
            continue

        tmpl, kwargs = plan.keys[key]
        call = f"tr({sv}, {json.dumps(key)}"
        for name, expr in kwargs:
            call += f", {name}={expr}"
        call += ")"

        # `f"..."`/`rf"..."`: col_offset tro thang vao prefix → dung mot cong thuc cho ca hai
        start = _offset(src, node.lineno, node.col_offset)
        end = _offset(src, node.end_lineno, node.end_col_offset)
        old = src[start:end]
        seg = ast.get_source_segment(src, node)          # do dung theo byte UTF-8
        if seg is None or old != seg:
            plan.manual.append({**f, "reason": f"cat nguon lech voi AST: {old[:28]!r} != {str(seg)[:28]!r}"})
            continue
        if isinstance(node, ast.Constant) and not isinstance(node.value, str):
            continue
        plan.edits.append({"start": start, "end": end, "replace": call, "key": key,
                           "line": f["line"], "old": old})

    # Loai key chi xuat hien trong manual/deferred (khong co edit nao tro toi)
    kept = {e["key"] for e in plan.edits}
    plan.keys = {k: v for k, v in plan.keys.items() if k in kept}
    plan.text_to_key = {t: k for t, k in plan.text_to_key.items() if k in kept}
    return plan


def _check_translation_placeholders(key: str, vi_tmpl: str, translated: str) -> bool:
    return sorted(PH_RE.findall(vi_tmpl)) == sorted(PH_RE.findall(translated))


def apply_plan(plan: Plan, translations: dict[str, dict], write_code: bool = True,
               write_locales: bool = True) -> list[str]:
    """Ghi code + locale. Tra ve danh sach loi (empty = ok)."""
    problems: list[str] = []
    path = ROOT / plan.rel
    if write_code:
        src = read_raw(path)
        for e in sorted(plan.edits, key=lambda x: -x["start"]):
            src = src[: e["start"]] + e["replace"] + src[e["end"]:]
        try:
            ast.parse(src)
        except SyntaxError as ex:
            return [f"KHONG ghi: {plan.rel} sau khi thay the bi loi cu phap: {ex}"]
        write_raw(path, src)

    glossary = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8")) if GLOSSARY_PATH.exists() else {}
    for lang in LANGS:
        p = LOCALES_DIR / f"{lang}.json"
        raw = read_raw(p)
        data = json.loads(raw)
        nl = dominant_newline(raw)
        add: list[tuple[str, str]] = []
        for key, (tmpl, _kw) in sorted(plan.keys.items()):
            if key in data:
                continue
            if lang == "vi":
                add.append((key, tmpl))
                continue
            alt = translations.get(key, {}).get(lang)
            if alt is None:
                alt = glossary.get(tmpl, {}).get(lang)
            if alt is None:
                problems.append(f"thieu dich {lang} cho {key}")
                continue
            if not _check_translation_placeholders(key, tmpl, alt):
                problems.append(f"placeholder lech (vi vs {lang}) cho {key}: {tmpl!r} vs {alt!r}")
                continue
            add.append((key, alt))
        if add and write_locales:
            write_raw(p, append_to_json_object(raw, add, nl))
        elif add:
            problems.append(f"{lang}: bo qua {len(add)} key (write_locales=False)")
    return problems


def append_to_json_object(raw: str, items: list[tuple[str, str]], nl: str) -> str:
    """Them key vao CUOI object JSON, giu nguyen thu tu cu + line ending.

    Ly do khong dung `json.dumps(sort_keys=True)`: locales/*.json trong repo KHONG
    sap xep theo key (nhom theo module, do nguoi viet), tai tao toan bo se sinh
    diff 1600 dong che mat thay doi that.
    """
    end = raw.rstrip().rfind("}")
    head = raw[:end].rstrip()
    lines = [f'  {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)}' for k, v in items]
    if head.endswith("{"):        # object rong
        return "{" + nl + ("," + nl).join(lines) + nl + "}" + nl
    return head + "," + nl + ("," + nl).join(lines) + nl + "}" + nl


def report(plan: Plan, verbose: bool = True):
    print(f"== {plan.rel}: {len(plan.edits)} thay the | {len(plan.keys)} key moi | "
          f"{len(plan.text_to_key)} canh bao doc nhat | {len(plan.manual)} manual | {len(plan.deferred)} deferred(tr kwargs)")
    if verbose and plan.manual:
        print("  CAN LAM TAY:")
        for m in plan.manual[:30]:
            print(f"   L{m['line']:>4} {m['reason'][:56]:56} {m['text'][:50]!r}")
        if len(plan.manual) > 30:
            print(f"   ... con {len(plan.manual) - 30}")
    if verbose and plan.deferred:
        print("  deferred (trong tr kwargs):")
        for m in plan.deferred[:10]:
            print(f"   L{m['line']:>4} {m['text'][:70]!r}")
    if verbose:
        print("  MAU:")
        for e in plan.edits[:8]:
            print(f"   L{e['line']:>4} {e['old'][:52]!r}\n        -> {e['replace'][:76]!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "plan", "apply"])
    ap.add_argument("file")
    ap.add_argument("--prefix")
    ap.add_argument("--translations")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if args.cmd == "fetch":
        inserts = plan_fetches(args.file)
        print(f"== {args.file}: {len(inserts)} ham thieu bien mang ngon ngu server")
        for i in inserts:
            print(f"   dong {i['at_index']:>4} ({i['name']}): {i['code']}")
        if not inserts or args.dry_run:
            return 0
        n = apply_fetches(args.file, inserts)
        print(f"-> da chen {n} dong `gs = await async_get_guild_settings(...)`")
        return 0

    plan = plan_file(args.file, args.prefix)
    report(plan, verbose=not args.quiet)
    if args.cmd == "plan":
        out = ROOT / "scripts" / "_i18n_pending.json"
        out.write_text(json.dumps({
            "file": plan.rel,
            "keys": {k: {"vi": v[0], "placeholders": v[1]} for k, v in plan.keys.items()},
            "manual": plan.manual,
            "deferred": plan.deferred,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"-> ke hoach day du: {out}")
        return 0

    translations = (json.loads(Path(args.translations).read_text(encoding="utf-8"))
                    if args.translations else {})
    if args.dry_run:
        problems = apply_plan(plan, translations, write_code=False, write_locales=False)
        print(f"DRY-RUN: {len(problems)} van de")
        for x in problems[:20]:
            print("   ", x)
        return 0
    problems = apply_plan(plan, translations)
    for x in problems[:40]:
        print("  !", x)
    print(f"-> da ghi {plan.rel} + {len(plan.keys)} key x 6 locale, {len(problems)} van de con lai")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
