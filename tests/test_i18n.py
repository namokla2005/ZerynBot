"""Tests cho i18n.py — parity 6 ngôn ngữ, placeholder đồng nhất, fallback chain."""
import json
import re

from i18n import i18n, tr, t

_LANGS = ["vi", "en", "zh", "es", "pt", "fr"]


def _flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def _load_locales():
    import os
    locales_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "locales"
    )
    return {
        lang: _flatten(json.load(open(f"{locales_dir}/{lang}.json", encoding="utf-8")))
        for lang in _LANGS
    }


def test_six_languages_loaded():
    supported = i18n.get_supported_languages()
    for lang in _LANGS:
        assert lang in supported


def test_key_parity_all_languages():
    data = _load_locales()
    ref = set(data["en"].keys())
    for lang in _LANGS:
        keys = set(data[lang].keys())
        assert keys == ref, f"{lang}.json lệch {len(ref ^ keys)} key so với en.json"


def test_placeholder_parity():
    """Placeholder {var} phải giống nhau giữa các ngôn ngữ cho cùng 1 key."""
    data = _load_locales()
    for key, en_val in data["en"].items():
        en_ph = set(re.findall(r"{(\w+)}", str(en_val)))
        if not en_ph:
            continue
        for lang in _LANGS:
            other_ph = set(re.findall(r"{(\w+)}", str(data[lang].get(key, ""))))
            assert en_ph == other_ph, f"key '{key}' lệch placeholder ở {lang}.json"


def test_translate_english():
    msg = t("common.no_permission", "en")
    assert isinstance(msg, str) and msg and "common.no_permission" != msg


def test_fallback_to_vietnamese_for_unknown_lang():
    msg_def = t("common.no_permission", "xx")  # lang không tồn tại → fallback vi
    msg_vi = t("common.no_permission", "vi")
    assert msg_def == msg_vi


def test_missing_key_returns_key_or_default():
    assert t("khong.co.key.nay", "en") == "khong.co.key.nay"
    assert t("khong.co.key.nay", "en", default="dự phòng") == "dự phòng"


def test_tr_accepts_settings_dict_and_lang_str():
    s1 = tr({"language": "en"}, "common.no_permission")
    s2 = tr("en", "common.no_permission")
    assert s1 == s2


def test_tr_formats_placeholders():
    # key biết chắc có placeholder — nếu không còn, test này vẫn không crash
    data = _load_locales()
    key_with_ph = next(k for k, v in data["en"].items() if "{user}" in str(v))
    rendered = tr("en", key_with_ph, user="Tester")
    assert "{user}" not in rendered
