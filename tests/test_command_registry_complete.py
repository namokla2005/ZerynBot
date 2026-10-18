# -*- coding: utf-8 -*-
"""Guard cho registry lệnh `_COMMANDS_DATA` — nguồn tri thức của AI Chat, /help và /docs.

Registry là file data thuần, không có đoạn nào import nó lúc chạy nên lệch không gây
crash: thêm lệnh mới mà quên ghi ở đây thì bot vẫn chạy mượt, chỉ là AI trả lời
"không có lệnh đó" và `/help <lệnh>` báo không tìm thấy. Lệch này đã xảy ra thật —
6 lệnh music cốt lõi (/pause, /skip, /queue, /volume, /nowplaying, /shuffle) và 7 lệnh
con /playlist nằm ngoài registry, trong khi `ai_knowledge.py` lại DẶN AI liệt kê đúng
những lệnh nó chưa từng được nạp.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import command_registry_audit as audit  # noqa: E402


def test_every_command_declared_in_cogs_is_in_the_registry():
    missing, _stale, actual, _reg = audit.drift()
    assert not missing, (
        "Những lệnh này đang chạy thật nhưng AI Chat / /help / /docs không biết tới:\n"
        + "\n".join(f"  /{k}  <- {', '.join(actual[k])}" for k in missing)
    )


def test_registry_has_no_ghost_commands():
    _missing, stale, _actual, reg = audit.drift()
    assert not stale, (
        "Registry quảng bá những lệnh không còn tồn tại trong code:\n"
        + "\n".join(f"  /{k}  (danh mục {reg[k]})" for k in stale)
    )


def test_auditor_resolved_every_declaration():
    """Cog khai báo lệnh theo kiểu mới thì auditor phải hô báo, không được im lặng bỏ qua."""
    unresolved = []
    for path in sorted(audit.COGS.glob("*.py")):
        for name, kind, _fname, _deco in audit.analyze(path):
            if kind == "unresolved" or name.startswith("?"):
                unresolved.append(f"{path.name}: {name}")
    assert not unresolved, (
        "Không xác định được lệnh cha của các khai báo sau nên chúng bị bỏ qua:\n"
        + "\n".join(unresolved)
    )


def test_registry_entries_are_renderable():
    """Mỗi entry phải đủ dữ liệu để /help và modal /docs render, không có chỗ trống."""
    bad = []
    seen = set()
    for cat in audit.registry_raw():
        for cmd in cat.get("commands", []):
            name = cmd.get("name", "")
            key = name.strip().lower()
            if key in seen:
                bad.append(f"{name!r}: trùng tên (COMMANDS_BY_NAME sẽ ghi đè nhau)")
            seen.add(key)
            for field in ("desc", "usage", "example"):
                if not (cmd.get(field) or "").strip():
                    bad.append(f"{name!r}: thiếu '{field}'")
            usage = cmd.get("usage", "")
            if usage == "(Dashboard)":
                continue
            if not usage.startswith("/"):
                bad.append(f"{name!r}: usage phải bắt đầu bằng '/' -> {usage!r}")
            elif not usage.lower().lstrip("/").startswith(key):
                bad.append(f"{name!r}: usage {usage!r} không khớp tên lệnh")
            for arg in cmd.get("args", []):
                if not arg.get("name") or not arg.get("desc") or not arg.get("type"):
                    bad.append(f"{name!r}: tham số thiếu name/desc/type: {arg}")
    assert not bad, "\n".join(bad)


def test_ai_payload_lists_every_registry_command():
    """System prompt của AI phải chứa từng usage — đó là thứ model thực sự nhìn thấy."""
    from ai_knowledge import get_zerynbot_knowledge

    knowledge = get_zerynbot_knowledge()
    missing = []
    for cat in audit.registry_raw():
        for cmd in cat.get("commands", []):
            if cmd.get("usage") == "(Dashboard)":
                continue
            path = "/" + cmd["name"].lower()
            if path not in knowledge:
                missing.append(f"{path} (usage ghi {cmd.get('usage')!r})")
    assert not missing, "AI không được nạp các lệnh: " + ", ".join(missing)


def test_ai_payload_command_count_matches_registry():
    """Con số AI tự tuyên bố ('DANH MỤC ĐẦY ĐỦ N LỆNH') phải là số thật, không hardcode."""
    from ai_knowledge import get_zerynbot_knowledge

    knowledge = get_zerynbot_knowledge()
    match = re.search(r"DANH MỤC ĐẦY ĐỦ (\d+) LỆNH", knowledge)
    assert match, "Không thấy dòng đếm lệnh trong bản đồ tri thức AI"
    real = sum(len(c.get("commands", [])) for c in audit.registry_raw())
    assert int(match.group(1)) == real, (
        f"AI báo {match.group(1)} lệnh trong khi registry có {real}"
    )


def test_ai_never_advises_a_command_that_does_not_exist():
    """Mỗi `/token` trong phần chỉ dẫn của bản đồ tri thức phải là lệnh có thật."""
    from ai_knowledge import get_zerynbot_knowledge

    known = set(audit.registry_commands()) | {"np", "cq"}      # bí danh thật của nowplaying/clearqueue
    advice = get_zerynbot_knowledge().split("NGUYÊN TẮC PHẢN HỒI")[-1]
    ghosts = sorted({
        m.group(1).lower()
        for m in re.finditer(r"(?<![\w/`])/([a-z][a-z0-9_]+)", advice)
        if m.group(1).lower() not in known
    })
    assert not ghosts, f"Chỉ dẫn AI gợi ý lệnh ma: {ghosts}"


def test_every_registry_command_has_a_translated_description():
    """/docs render `cmd.<ten>.desc` cho 6 ngon ngu; thieu key la trang en/zh/fr lo
    chu Tieng Viet — chinh la loi i18n da sua ca thang nay.

    Vi du that: 23 lenh (toan bo `verify *`, `automods raid*`, `work`, `fish`, `hunt`,
    `inventory`, `sell`, `topmusic`, `ticket`, `lang`, `config`, `sync`, `backup`) khong
    co key, nen khong test nao bat duoc khi them lenh moi ma khong dich.
    """
    import json

    locales = {}
    for lang in ("vi", "en", "zh", "es", "pt", "fr"):
        with open(ROOT / "locales" / f"{lang}.json", encoding="utf-8") as f:
            locales[lang] = json.load(f)

    missing = []
    for cat in audit.registry_raw():
        for cmd in cat.get("commands", []):
            key = f"cmd.{cmd['name'].replace(' ', '_')}.desc"
            for lang, data in locales.items():
                if key not in data:
                    missing.append(f"{key} [{lang}]")
                elif lang == "vi" and data[key] != cmd["desc"] and key not in KNOWN_DESC_DRIFT:
                    missing.append(f"{key} [vi] khop voi desc trong registry")
    assert not missing, "Thieu/lech ban dich mo ta lenh:\n" + "\n".join(missing[:40])


# 19 mo ta cu da duoc viet lai trong `commands_data.py` ma khong cap nhat lai 6 locale
# (registry phong phu hon: them cooldown, them chi dan...). Dong bang nay CHAT: them
# key moi ma noi dung vi khong khop registry la test do, muon them phai chu dich.
KNOWN_DESC_DRIFT = {
    "cmd.remindme.desc",
    "cmd.reactionroles.desc",
    "cmd.search.desc",
    "cmd.lofi.desc",
    "cmd.deposit.desc",
    "cmd.withdraw.desc",
    "cmd.ask.desc",
    "cmd.summarize.desc",
    "cmd.warn.desc",
    "cmd.slap.desc",
    "cmd.feed.desc",
    "cmd.cuddle.desc",
    "cmd.highfive.desc",
    "cmd.marry.desc",
    "cmd.divorce.desc",
    "cmd.profile.desc",
    "cmd.birthday_set.desc",
    "cmd.birthday_list.desc",
    "cmd.birthday_remove.desc",
}
