"""i18n_audit.py — Kiem ke thua chuoi tieng Viet hardcode bang AST (duyet chieu xuong).

Muc dich: tach dung "chuoi nguoi dung nhin thay qua Discord" (can de-hardcode) khoi
chuoi log / docstring / du lieu noi bo (khong can). Regex tho phan loai sai vi f-string
nam trong `ctx.send(...)`, Embed build bang bien trung gian, View/Button long trong
kwarg `view=` cua `ctx.send()`...

Quy tac phan loai dat trong bang SPEC: moi kieu loi goi khai bao ro
    - role:        DISCORD | STORED | INTERNAL | UNCLEAR
    - kwarg nao    la van ban hien thi
    - arg vi tri   nao la van ban hien thi

Ung dung:
    python scripts/i18n_audit.py                              # tong hop theo file
    python scripts/i18n_audit.py --role DISCORD bot/cogs/verify.py
    python scripts/i18n_audit.py --json /tmp/manifest.json
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

VI_MARK = re.compile(r"[àáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ]", re.I)

DISCORD, STORED, INTERNAL, UNCLEAR = "DISCORD", "STORED", "INTERNAL", "UNCLEAR"
CATALOG = "CATALOG"
META = "META"

# Kwarg KHONG phai van ban nguoi dung (duoc phat trong moi nguyen tac).
META_KWARGS = {
    "ephemeral", "delete_after", "tts", "silent", "allowed_mentions", "reference",
    "message_reference", "wait", "mention_author", "suppress", "file", "files",
    "attachments", "style", "url", "custom_id", "disabled", "row", "timeout", "color",
    "colour", "timestamp", "inline", "icon_url", "thumbnail_url", "min_values",
    "max_values", "required", "min_length", "max_length", "ids", "channel", "user",
    "member", "guild", "reason", "poll", "stickers", "with_message", "voice",
    "check", "on_submit", "permissions", "slowmode_seconds", "auto_archive_duration",
    "default_archive_duration", "category", "position", "overwrites", "mentionable",
    "hoist", "colour", "bytes", "filename", "as_file", "spm", "options", "values",
}
SEND_METHODS = {
    "send", "reply", "respond", "defer", "defer_update", "edit", "edit_deferred",
    "send_modal", "send_message", "send_embed", "update", "followup_send", "send_file",
}
SEND_TEXT_KWARGS = {"content", "embed", "embeds", "view", "components", "text", "title", "description"}
EMBED_KWARGS = {"title", "description"}
EMBED_METHOD_KWARGS = {"add_field": {"name", "value"}, "set_footer": {"text"}, "set_author": {"name"}}
UI_TEXT_KWARGS = {
    "Button": {"label"},
    "Option": {"label", "description"},
    "Select": {"placeholder"},
    "Modal": {"title"},
    "TextInput": {"label", "placeholder", "value", "default"},
    "StringSelect": {"placeholder"},
}
UI_COMPONENTS = set(UI_TEXT_KWARGS) | {"ChannelSelect", "RoleSelect", "UserSelect", "MentionableSelect"}
# Phien ban thuong cho decorator: @discord.ui.button(label=...), @app_commands.describe(...)
UI_COMPONENTS |= {c.lower() for c in UI_COMPONENTS}
UI_TEXT_KWARGS = {**{k.lower(): v for k, v in UI_TEXT_KWARGS.items()}, **UI_TEXT_KWARGS}
LOG_FUNCS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log", "print"}
DB_PREFIX = ("async_", "increment_", "set_", "add_", "create_", "update_", "insert_", "delete_", "remove_")
CREATE_OBJECT_METHODS = {"create_role", "create_text_channel", "create_voice_channel",
                         "create_thread", "create_forum", "create_stage_channel", "create_category"}
COMMAND_META_KWARGS = {"description", "name", "human_name", "extra_args"}


@dataclass
class Spec:
    role: str
    why: str
    kwargs: set[str] | None = None      # None = "moi thu khong thuoc META_KWARGS|drop"
    positional: set[int] = field(default_factory=lambda: {0})
    walk_view: bool = False             # xuong View/Select de tim label long ben trong
    drop: frozenset[str] = frozenset()  # bo sung ten kwarg khong phai van ban


COMMAND_DECORATORS = {"command", "hybrid_command", "hybrid_group", "group", "slash_command",
                      "describe", "param"}
COMMAND_META_DROP = frozenset({
    "aliases", "hidden", "guild_ids", "cooldown_after", "cooldown_rate", "cooldown_key",
    "enabled", "require_var_positional", "rest_is_raw", "case_insensitive", "with_feedback",
    "bypass.cooldown", "nsfw", "global_name", "parent", "cls", "self", "auto_log",
})


def resolve(call: ast.Call) -> Spec | None:
    full, last = call_name(call)
    attr = call.func.attr if isinstance(call.func, ast.Attribute) else ""

    if last in LOG_FUNCS or full.startswith(("log.", "logger.", "logging.", "print")):
        return Spec(INTERNAL, f"log:{full}", kwargs=set(), positional=set())
    if last in EMBED_METHOD_KWARGS:
        return Spec(DISCORD, f"embed:{attr}", kwargs=EMBED_METHOD_KWARGS[attr], positional=set())
    if last in EMBED_CTOR:
        return Spec(DISCORD, f"embed:{full}", kwargs=EMBED_KWARGS, positional=set())
    if last in UI_COMPONENTS:
        return Spec(DISCORD, f"ui:{last}", kwargs=UI_TEXT_KWARGS.get(last, set()), positional=set())
    if last == "View" or last.endswith("View"):
        return Spec(DISCORD, f"view:{full}", kwargs=set(), positional={0}, walk_view=True)
    if attr in SEND_METHODS or last in SEND_METHODS:
        return Spec(DISCORD, f"send:{full}", kwargs=SEND_TEXT_KWARGS, positional={0})
    if last == "tr":
        return Spec(DISCORD, "tr:kwargs", kwargs=None, positional=set())
    if attr in COMMAND_DECORATORS or last in COMMAND_DECORATORS:
        # @commands.hybrid_command(name=..., description=...) va @app_commands.describe(x="...")
        # hiEN trong menu slash cua Discord. KHONG the dich theo tung server vi Discord
        # dang payload toan cau (sync 1 lan); phan nay da duoc i18n hoa o `commands_data.py`
        # + `cmd.*`/`help.*` trong locales cho /help va /docs → tach sang role META.
        return Spec(META, f"command-meta:{full}", kwargs=None, positional=set(), drop=COMMAND_META_DROP)
    if attr in CREATE_OBJECT_METHODS:
        return Spec(STORED, f"object:{full}", kwargs=None, positional=set())
    if last.startswith(DB_PREFIX) or full.startswith("db."):
        return Spec(STORED, f"db:{full}", kwargs=None, positional=set())
    return None


EMBED_CTOR = {"Embed"}


def call_name(call: ast.Call) -> tuple[str, str]:
    parts: list[str] = []
    f = call.func
    while isinstance(f, ast.Attribute):
        parts.append(f.attr)
        f = f.value
    if isinstance(f, ast.Name):
        parts.append(f.id)
    full = ".".join(reversed(parts))
    return full, (parts[0] if parts else "")


def is_vi(text: str) -> bool:
    return bool(text) and bool(VI_MARK.search(text))


def collect_sink_vars(func: ast.AST) -> set[str]:
    """Ten duoc dung truc tiep trong tham so cua mot sink (ctx.send/send/embed/ui).

    Can mot buoc du lieu vi `detail = "..."; await ctx.send(detail)` la cach viet
    thong dung nhat trong cog, neu khong thi `detail` bi xep vao UNCLEAR va bi bo
    qua khi de-hardcode.
    """
    names: set[str] = set()
    for n in ast.walk(func):
        if not isinstance(n, ast.Call):
            continue
        spec = resolve(n)
        if spec is None or spec.role != DISCORD:
            continue
        for a in list(n.args) + [kw.value for kw in n.keywords]:
            for sub in ast.walk(a):
                if isinstance(sub, ast.Name):
                    names.add(sub.id)
    return names


def helper_visible_params(container: ast.AST) -> dict[str, tuple[list[str], set[str]]]:
    """Ham trung gian co tham so chay vao sink → van ban o cho goi cung hien thi.

    Vi du `_handle_violation(message, reason)` cua automod render `reason` vao embed
    vi pham; neu khong phat hien dieu nay thi `Spam chu IN HOA` bi xep UNCLEAR va
    khi de-hardcode se sot lai chuoi tieng Viet tren Discord.
    """
    out: dict[str, tuple[list[str], set[str]]] = {}
    funcs = [n for n in ast.walk(container)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for fn in funcs:
        params = [a.arg for a in list(fn.args.posonlyargs) + list(fn.args.args) if a.arg != "self"]
        if not params:
            continue
        used: set[str] = set()
        for n in ast.walk(fn):
            if not isinstance(n, ast.Call):
                continue
            spec = resolve(n)
            if spec is None or spec.role != DISCORD:
                continue
            for a in list(n.args) + [kw.value for kw in n.keywords]:
                for sub in ast.walk(a):
                    if isinstance(sub, ast.Name):
                        used.add(sub.id)
        visible = {p for p in params if p in used}
        if visible:
            out[fn.name] = (params, visible)
    return out


class Visitor(ast.NodeVisitor):
    def __init__(self, path: Path):
        self.rel = str(path.relative_to(ROOT)).replace("\\", "/")
        self.findings: list[dict] = []
        self.embed_vars: set[str] = set()
        self._seen: set[int] = set()
        self._done: set[int] = set()
        self._sink_vars: set[str] = set()
        self._helpers: dict[str, tuple[list[str], set[str]]] = {}

    # ── ghi nhan ──────────────────────────────────────────────────────────
    def _emit(self, node, text: str, role: str, why: str, kind: str):
        self.findings.append({
            "file": self.rel, "line": getattr(node, "lineno", 0),
            "col": getattr(node, "col_offset", 0), "kind": kind, "text": text,
            "role": role, "why": why, "raw": _unparse(node)[:180],
        })

    def _leaf(self, node, role: str, why: str) -> bool:
        """True neu node la van ban (da ghi) hoac can xuong. Khong phai van ban → False."""
        if id(node) in self._done:
            return True
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if is_vi(node.value):
                self._done.add(id(node))
                self._emit(node, node.value, role, why, "str")
            return True
        if isinstance(node, ast.JoinedStr):
            plain = "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
            if is_vi(plain):
                self._done.add(id(node))
                self._emit(node, plain, role, why, "fstr")
            for form in node.values:
                if isinstance(form, ast.FormattedValue):
                    self._walk_expr(form.value, role, f"{why}(f-expr)")
            return True
        return False

    def _walk_expr(self, node, role: str, why: str):
        if node is None or isinstance(node, ast.Load):
            return
        if self._leaf(node, role, why):
            return
        if isinstance(node, ast.Call):
            self._handle_call(node, fallback=(role, why))
            return
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            for el in node.elts:
                self._walk_expr(el, role, f"{why}[]")
            return
        if isinstance(node, ast.Dict):
            for v in node.values:
                self._walk_expr(v, role, f"{why}(dict)")
            return
        for child in ast.iter_child_nodes(node):
            self._walk_expr(child, role, f"{why}({type(child).__name__})")

    # ── loi goi ───────────────────────────────────────────────────────────
    def _handle_call(self, call: ast.Call, fallback: tuple[str, str] | None = None):
        _full, last = call_name(call)
        spec = resolve(call)
        if spec is None:
            info = self._helpers.get(last)
            if info:
                params, visible = info
                spec = Spec(
                    DISCORD, f"helper:{last}", kwargs=None,
                    positional={i for i, p in enumerate(params) if p in visible},
                    drop=frozenset(set(params) - visible),
                )
            else:
                role, why = fallback if fallback else (UNCLEAR, f"call:{call_name(call)[1]}")
                spec = Spec(role, why, kwargs=None, positional=set())
        for i, a in enumerate(call.args):
            r = spec.role if i in spec.positional else UNCLEAR
            if spec.walk_view and isinstance(a, (ast.List, ast.Tuple)):
                r = spec.role
            self._walk_expr(a, r, f"{spec.why}[arg{i}]")
        for kw in call.keywords:
            name = kw.arg or ""
            if spec.kwargs is not None:
                if name in spec.kwargs:
                    self._walk_expr(kw.value, spec.role, f"{spec.why}:{name}")
                elif spec.walk_view and name in {"children", "items"}:
                    self._walk_expr(kw.value, spec.role, f"{spec.why}:{name}")
                else:
                    self._walk_expr(kw.value, UNCLEAR, f"{spec.why}:{name}(non-text)")
            elif name in META_KWARGS or name in spec.drop:
                self._walk_expr(kw.value, INTERNAL, f"{spec.why}:{name}(meta)")
            else:
                self._walk_expr(kw.value, spec.role, f"{spec.why}:{name}")

    def visit_Call(self, node: ast.Call):
        self._handle_call(node)

    # ── gan bien Embed de `embed = discord.Embed(); embed.add_field(...)` ──
    def visit_Assign(self, node: ast.Assign):
        targets = [t for t in getattr(node, "targets", []) if isinstance(t, ast.Name)]
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target]
        if isinstance(node.value, ast.Call):
            last = call_name(node.value)[1]
            if last in EMBED_CTOR or last in UI_COMPONENTS or last.endswith("View"):
                for t in targets:
                    self.embed_vars.add(t.id)
            self.generic_visit(node)
            return
        # `detail = "..." + f"..."` roi `ctx.send(detail)` → van ban hien thi, phai theo 1 buoc
        if any(t.id in self._sink_vars for t in targets):
            self._walk_expr(node.value, DISCORD, "var-to-sink")
            return
        self.generic_visit(node)

    visit_AnnAssign = visit_Assign

    # ── docstring: khong phai van ban Discord ─────────────────────────────
    def visit_Module(self, node: ast.Module):
        self._skip_docstring(node.body)
        for stmt in node.body:
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                names = [t.id for t in getattr(stmt, "targets", []) if isinstance(t, ast.Name)]
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    names.append(stmt.target.id)
                if names and all(n.isupper() for n in names):
                    self._mark_catalog(stmt.value)
        self.generic_visit(node)

    def _mark_catalog(self, node):
        """Bang gia (shop items, fish table, AI persona...) dung o cap module.

        Van la chuoi hien thi, nhung chuyen chung sang i18n keo theo DU LIEU DA LUU
        (ten item da nam trong economy_inventory / thong ke) → can mot quyet dinh
        chuyen sau, khong gop voi thong diep.
        """
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and is_vi(sub.value):
                self._done.add(id(sub))
                self._emit(sub, sub.value, CATALOG, "catalog-data", "str")
            elif isinstance(sub, ast.JoinedStr):
                plain = "".join(v.value for v in sub.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
                if is_vi(plain):
                    self._done.add(id(sub))
                    self._emit(sub, plain, CATALOG, "catalog-data", "fstr")

    def visit_ClassDef(self, node: ast.ClassDef):
        self._skip_docstring(node.body)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._skip_docstring(node.body)
        self._sink_vars = collect_sink_vars(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def _skip_docstring(self, body):
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            self._seen.add(id(body[0].value))

    def visit_Expr(self, node: ast.Expr):
        if isinstance(node.value, ast.Constant) and id(node.value) in self._seen:
            return
        self.generic_visit(node)

    def generic_visit(self, node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.Constant, ast.JoinedStr)):
                self._leaf(child, UNCLEAR, "free-standing")
                continue
            self.visit(child)


def _unparse(node) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def audit_file(path: Path) -> list[dict]:
    src = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        print(f"!! {path}: SyntaxError {e}", file=sys.stderr)
        return []
    v = Visitor(path)
    v._helpers = helper_visible_params(tree)
    v.visit(tree)
    return v.findings


def iter_targets(paths: list[str]) -> list[Path]:
    if paths:
        out: list[Path] = []
        for p in paths:
            q = Path(p) if Path(p).is_absolute() else ROOT / p
            out.extend(sorted(q.rglob("*.py")) if q.is_dir() else [q])
        return out
    return sorted((ROOT / "bot").rglob("*.py"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--json", help="ghi manifest day du")
    ap.add_argument("--budget", action="store_true",
                    help="ghi tests/i18n_budget.json: so chuoi DISCORD con lai cua tung file (dong bang ngan sach)")
    ap.add_argument("--role", action="append")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    findings: list[dict] = []
    for f in iter_targets(args.paths):
        if "__pycache__" in str(f):
            continue
        findings.extend(audit_file(f))

    by_file: dict[str, Counter] = defaultdict(Counter)
    total: Counter = Counter()
    for x in findings:
        by_file[x["file"]][x["role"]] += 1
        total[x["role"]] += 1

    print(f"{'file':46} {'DISCORD':>8} {'META':>6} {'CATALOG':>8} {'INT':>5} {'UNCLEAR':>8}")
    for file, c in sorted(by_file.items(), key=lambda kv: (-kv[1][DISCORD], -sum(kv[1].values()))):
        print(f"{file:46} {c[DISCORD]:>8} {c[META]:>6} {c[CATALOG]:>8} {c[INTERNAL]:>5} {c[UNCLEAR]:>8}")
    print("-" * 84)
    print(f"{'TONG':46} {total[DISCORD]:>8} {total[META]:>6} {total[CATALOG]:>8} {total[INTERNAL]:>5} {total[UNCLEAR]:>8}")

    if args.budget:
        keep = {f: c[DISCORD] for f, c in by_file.items() if c[DISCORD] > 0}
        out = ROOT / "tests" / "i18n_budget.json"
        # GIU LAI cac entry = 0 (file da migrate xong) de test "da migrate thi phai sach"
        # con dat ten duoc; file tung co chuoi nay da sach → ghi 0 de giu milestone.
        prev: dict = {}
        if out.exists():
            prev = json.loads(out.read_text(encoding="utf-8"))
        merged = dict(keep)
        for f in prev:
            if f not in merged:
                merged[f] = 0
        out.write_text(json.dumps(dict(sorted(merged.items(), key=lambda kv: -kv[1])),
                                  ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        done = sum(1 for v in merged.values() if v == 0)
        print(f"-> ngan sach: {sum(merged.values())} chuoi con lai / {len(keep)} file, "
              f"{done} file da sach — ghi {out.name}")
        return 0

    if args.json:
        sel = [x for x in findings if not args.role or x["role"] in args.role]
        if args.limit:
            sel = sel[: args.limit]
        Path(args.json).write_text(json.dumps(sel, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"-> ghi {len(sel)} dong vao {args.json}")
    elif args.role:
        shown = 0
        for x in findings:
            if x["role"] in args.role:
                print(f"{x['file']}:{x['line']:>4} [{x['why'][:36]:36}] {x['text'][:78]!r}")
                shown += 1
                if args.limit and shown >= args.limit:
                    break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
