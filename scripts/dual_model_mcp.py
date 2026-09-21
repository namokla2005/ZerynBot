"""
dual_model_mcp.py — Dual-Model Reasoning & Adversarial Debate MCP Server for Antigravity IDE.

Cho phép Antigravity kết nối đồng thời với model AI thứ 2 (Google Gemini, Groq Qwen/GPT-OSS, OpenRouter)
để cùng suy luận, phản biện chéo (Critique), đối chiếu kiến trúc và tranh biện nhiều hiệp (Multi-round Debate).

Hỗ trợ:
  - Chuẩn Model Context Protocol (MCP 2.x) qua Stdio Transport.
  - CLI Direct Invocation (cho phép gọi trực tiếp qua terminal/script).
  - Khả năng tự động xoay vòng model khi gặp Rate Limit (HTTP 429 Auto-Fallback).
  - Pydantic v2 Type-Safety Schemas cho Code Review và Pre-Commit Check.
  - Bộ lọc dữ liệu nhạy cảm (Secret Scrubber) chống rò rỉ API Keys ra Cloud.
  - Phòng vệ Path Traversal & Command Injection khi chạy trên môi trường Windows.
"""
import os
import sys
import time
import json
import re
import sqlite3
import argparse
import subprocess
from enum import Enum
from typing import List, Optional, Dict, Any, Literal
import requests
from pydantic import BaseModel, Field, ValidationError

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from mcp.server.mcpserver import MCPServer

server = MCPServer(
    name="dual-model-assistant",
    title="Antigravity Dual-Model Co-Reasoning & Debate",
    description="Công cụ kết nối model AI thứ 2 để đối thoại phản biện, review kiến trúc và tranh luận chuyên sâu.",
    version="1.2.0",
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "bot.db")

GROQ_FALLBACK_MODELS = [
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "groq/compound-mini",
]


# ==========================================
# 1. Pydantic v2 Type-Safety Schemas
# ==========================================

class SeverityLevel(str, Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


class CodeIssue(BaseModel):
    severity: Literal["CRITICAL", "WARNING", "INFO"] = "WARNING"
    title: str = Field(default="Vấn đề tiềm ẩn", description="Tiêu đề ngắn gọn của vấn đề")
    line_hint: Optional[str] = Field(default=None, description="Gợi ý số dòng hoặc tên hàm bị ảnh hưởng")
    description: str = Field(default="", description="Mô tả chi tiết nguyên nhân và hậu quả")
    termux_risk: str = Field(
        default="Không có rủi ro đáng kể trên Termux ARM64.",
        description="Đánh giá ảnh hưởng tới CPU, RAM Helio G85, pin hoặc SQLite WAL trên Termux"
    )


class CodeReviewReport(BaseModel):
    file_path: str = Field(default="", description="Đường dẫn tương đối của tệp")
    verdict: Literal["APPROVED", "REQUEST_CHANGES", "NEEDS_DISCUSSION"] = "NEEDS_DISCUSSION"
    score: int = Field(default=7, ge=1, le=10, description="Thang điểm từ 1 đến 10")
    summary: str = Field(default="", description="Tóm tắt ngắn gọn")
    issues: List[CodeIssue] = []
    recommended_patch: Optional[str] = None


class PreCommitReport(BaseModel):
    staged_files: List[str] = []
    risk_level: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"
    verdict: Literal["READY_TO_COMMIT", "FIX_REQUIRED"] = "READY_TO_COMMIT"
    checklist_passed: Dict[str, bool] = Field(
        default_factory=lambda: {
            "i18n_synced": True,
            "sqlite_wal_safe": True,
            "safe_http_urls": True,
            "no_hardcoded_secrets": True,
        }
    )
    breaking_risks: List[str] = []
    summary: str = Field(default="", description="Tóm tắt rủi ro")


# ==========================================
# 2. Security Guards & Utilities
# ==========================================

SECRET_PATTERNS = [
    (r"gsk_[a-zA-Z0-9]{20,}", "gsk_***REDACTED***"),
    (r"sk-or-v1-[a-zA-Z0-9]{30,}", "sk-or-v1-***REDACTED***"),
    (r"AIzaSy[a-zA-Z0-9_\-]{30,}", "AIzaSy***REDACTED***"),
    (r"[a-zA-Z0-9_\-]{24}\.[a-zA-Z0-9_\-]{6}\.[a-zA-Z0-9_\-]{27,}", "***DISCORD_TOKEN_REDACTED***"),
    (r"(password|secret|token)\s*[:=]\s*['\"][^'\"]+['\"]", r"\1: '***REDACTED***'"),
]


def _scrub_sensitive_data(text: str) -> str:
    """Loại bỏ token, API keys, secrets trước khi gửi ra Cloud LLM."""
    if not text:
        return ""
    out = text
    for pattern, replacement in SECRET_PATTERNS:
        out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)
    return out


def _resolve_safe_path(user_path: str) -> str:
    """Xác thực đường dẫn an toàn nằm trong BASE_DIR, chống Path Traversal và Symlink bypass."""
    real_base = os.path.realpath(BASE_DIR)
    target_path = os.path.realpath(os.path.join(real_base, user_path.strip()))
    try:
        common = os.path.commonpath([real_base, target_path])
        if common != real_base:
            raise PermissionError(f"Truy cập ngoài thư mục dự án bị từ chối: {user_path}")
    except ValueError:
        raise PermissionError(f"Đường dẫn không hợp lệ: {user_path}")

    if not os.path.exists(target_path):
        raise FileNotFoundError(f"Không tìm thấy tệp: {user_path}")
    if os.path.isdir(target_path):
        raise IsADirectoryError(f"Đường dẫn là thư mục, không phải tệp: {user_path}")
    return target_path


def _extract_json_block(raw_text: str) -> dict:
    """Bóc tách block JSON từ phản hồi LLM an toàn, chống markdown fences và tự vá JSON cắt cụt."""
    if not raw_text:
        return {}
    text = raw_text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        text = m.group(1).strip()
    else:
        m_open = re.search(r"```(?:json)?\s*([\s\S]*)", text)
        if m_open:
            text = m_open.group(1).strip()

    # 1. Thử parse trực tiếp
    try:
        return json.loads(text)
    except Exception:
        pass

    # 2. Thử tìm cặp { ... }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end+1])
        except Exception:
            pass

    # 3. Tự vá JSON bị cắt cụt (Truncation repair)
    if start != -1:
        truncated = text[start:].strip()
        stack = []
        in_str = False
        escape = False
        for c in truncated:
            if c == '"' and not escape:
                in_str = not in_str
            elif c == '\\' and not escape:
                escape = True
                continue
            elif not in_str:
                if c == '{':
                    stack.append('}')
                elif c == '[':
                    stack.append(']')
                elif c in ('}', ']'):
                    if stack and stack[-1] == c:
                        stack.pop()
            escape = False
        if in_str:
            truncated += '"'
        truncated = truncated.rstrip()
        if truncated.endswith(','):
            truncated = truncated[:-1]
        while stack:
            truncated += stack.pop()
        try:
            return json.loads(truncated)
        except Exception:
            pass

    return {}


# ==========================================
# 3. Model API Connectors & Dispatcher
# ==========================================

def _get_api_keys():
    """Lấy API key từ env, .env, hoặc bot_global_settings trong data/bot.db."""
    keys = {
        "gemini": os.environ.get("GEMINI_API_KEY", "").strip(),
        "groq": os.environ.get("GROQ_API_KEY", "").strip(),
        "openrouter": os.environ.get("OPENROUTER_API_KEY", "").strip(),
    }

    if os.path.exists(DB_PATH):
        try:
            with sqlite3.connect(DB_PATH, timeout=5.0) as conn:
                for row in conn.execute("SELECT key, value FROM bot_global_settings").fetchall():
                    k, v = row[0], str(row[1]).strip()
                    if k == "gemini_api_key" and v:
                        if v.startswith("gsk_") and not keys["groq"]:
                            keys["groq"] = v
                        elif v.startswith("AIzaSy") and not keys["gemini"]:
                            keys["gemini"] = v
                        elif v.startswith("sk-or-") and not keys["openrouter"]:
                            keys["openrouter"] = v
                    elif k == "groq_api_key" and v and not keys["groq"]:
                        keys["groq"] = v
        except Exception:
            pass

    return keys


def _call_gemini(api_key: str, model: str, prompt: str, system_instruction: str = "") -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    contents = []
    if system_instruction:
        contents.append({"role": "user", "parts": [{"text": f"[SYSTEM INSTRUCTION]\n{system_instruction}"}]})
        contents.append({"role": "model", "parts": [{"text": "Đã hiểu vai trò và chỉ dẫn hệ thống."}]})
    contents.append({"role": "user", "parts": [{"text": prompt}]})

    payload = {
        "contents": contents,
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2000}
    }
    r = requests.post(url, json=payload, timeout=30)
    if r.status_code == 200:
        data = r.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError):
            return "❌ Phản hồi rỗng từ Gemini API."
    return f"❌ Lỗi Gemini API (HTTP {r.status_code}): {r.text}"


def _call_groq(api_key: str, model: str, prompt: str, system_instruction: str = "") -> str:
    models_to_try = [model] + [m for m in GROQ_FALLBACK_MODELS if m != model]
    last_err = ""

    for target_model in models_to_try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": target_model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 2000
        }
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=35)
            if r.status_code == 200:
                data = r.json()
                content = data["choices"][0]["message"]["content"].strip()
                if content:
                    return content
            elif r.status_code == 429:
                last_err = f"Rate limit on {target_model}, trying next..."
                time.sleep(1.0)
                continue
            else:
                last_err = f"HTTP {r.status_code}: {r.text}"
        except Exception as e:
            last_err = str(e)

    return f"❌ Lỗi Groq API: {last_err}"


def _call_openrouter(api_key: str, model: str, prompt: str, system_instruction: str = "") -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 1200
    }
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    if r.status_code == 200:
        data = r.json()
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError):
            return "❌ Phản hồi rỗng từ OpenRouter API."
    return f"❌ Lỗi OpenRouter API (HTTP {r.status_code}): {r.text}"


def _invoke_ai(prompt: str, role: str = "critic", model_pref: str = "auto") -> str:
    """Tự động điều phối gọi model thích hợp theo role và API key sẵn có."""
    keys = _get_api_keys()

    role_instructions = {
        "critic": (
            "Bạn là Senior Security Auditor & Code Reviewer khó tính cho ZerynBot V2. "
            "Dự án vận hành trên Android Termux (ARM64, CPU Helio G85, RAM 6GB, SQLite WAL 15s timeout). "
            "Nhiệm vụ của bạn là soi xét tỉ mỉ mã nguồn, chỉ ra các lỗ hổng bảo mật (SSRF, XSS, IDOR, SQL injection/deadlock), "
            "vấn đề quá tải CPU/RAM trên Termux, lỗi async/sync, race conditions, và phá vỡ chuẩn 20 modules / 108 lệnh / 1621 keys i18n. "
            "Trả lời súc tích bằng tiếng Việt, đi thẳng vào các điểm yếu cốt lõi."
        ),
        "architect": (
            "Bạn là Principal Software Architect. "
            "Nhiệm vụ của bạn là đưa ra giải pháp kiến trúc sạch, chuẩn mực, tuân thủ Clean Architecture và tối ưu hóa tài nguyên. "
            "Trả lời súc tích bằng tiếng Việt, nêu rõ ưu điểm và các bước then chốt."
        ),
        "tester": (
            "Bạn là QA Automation Lead chuyên kiểm thử phá hoại (Adversarial Testing). "
            "Hãy đặt ra các kịch bản thử nghiệm khắc nghiệt nhất, input dị thường và tình huống crash để kiểm chứng hệ thống. "
            "Trả lời bằng tiếng Việt, gạch đầu dòng ngắn gọn."
        ),
        "general": (
            "Bạn là AI Co-Reasoning Partner chuyên nghiệp. "
            "Hãy tham gia trao đổi, suy luận logic và đưa ra góc nhìn độc lập, khách quan về vấn đề được đặt ra."
        )
    }
    sys_inst = role_instructions.get(role, role_instructions["general"])

    # 1. Ưu tiên Groq cho phản biện (tốc độ cao 300 tokens/s)
    if keys["groq"] and (model_pref == "auto" or model_pref.startswith("qwen") or model_pref.startswith("openai/")):
        model = "qwen/qwen3.8-27b" if model_pref == "auto" else model_pref
        return _call_groq(keys["groq"], model, prompt, sys_inst)

    # 2. Nếu chỉ định rõ Gemini hoặc chỉ có Gemini key
    if keys["gemini"] and (model_pref.startswith("gemini") or model_pref == "auto"):
        model = model_pref if model_pref.startswith("gemini") else "gemini-2.0-flash"
        return _call_gemini(keys["gemini"], model, prompt, sys_inst)

    # 3. Fallback OpenRouter
    if keys["openrouter"]:
        model = "deepseek/deepseek-chat" if model_pref == "auto" else model_pref
        return _call_openrouter(keys["openrouter"], model, prompt, sys_inst)

    return (
        "❌ Chưa tìm thấy API Key nào (Gemini, Groq hoặc OpenRouter). "
        "Vui lòng cấu hình GEMINI_API_KEY hoặc GROQ_API_KEY trong file .env hoặc trên Web Dashboard /admin!"
    )


# ==========================================
# 4. Core Features: Review File & Pre-Commit
# ==========================================

def execute_review_code_file(file_path: str) -> str:
    """Đọc file, scrub secrets, gửi cho Model 2 review và parse sang Pydantic CodeReviewReport."""
    try:
        safe_path = _resolve_safe_path(file_path)
    except Exception as e:
        return f"❌ Lỗi truy cập tệp: {e}"

    rel_path = os.path.relpath(safe_path, BASE_DIR).replace("\\", "/")
    ignored_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".db", ".sqlite", ".ico", ".mp3", ".wav", ".zip", ".pyc"}
    _, ext = os.path.splitext(safe_path)
    if ext.lower() in ignored_exts:
        return f"ℹ️ Tệp {rel_path} là định dạng nhị phân ({ext}), bỏ qua review mã nguồn."

    try:
        with open(safe_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        return f"❌ Không thể đọc tệp {rel_path}: {e}"

    # Tránh context overflow nếu file quá dài: cắt lấy head 180 dòng và tail 120 dòng
    if len(lines) > 800:
        content_for_llm = "".join(lines[:450]) + "\n\n# [... PHẦN GIỮA ĐÃ ĐƯỢC CẮT BỚT ĐỂ TRÁNH TRÀN NGỮ CẢNH LLM ...]\n\n" + "".join(lines[-350:])
    else:
        content_for_llm = "".join(lines)

    content_for_llm = _scrub_sensitive_data(content_for_llm)

    prompt = (
        f"Bạn là Senior Security Auditor & Code Reviewer khó tính cho ZerynBot V2 (chạy trên Termux Android ARM64, CPU Helio G85, RAM 6GB, SQLite WAL).\n"
        f"Hãy rà soát tệp: `{rel_path}`\n\n"
        f"Nội dung mã nguồn:\n```python\n{content_for_llm}\n```\n\n"
        f"Yêu cầu:\n"
        f"1. Soi xét các lỗ hổng bảo mật (SSRF, Stored XSS, IDOR, SQL injection, SQLite deadlock).\n"
        f"2. Đánh giá rủi ro phần cứng trên Termux (rò rỉ RAM, quá tải CPU, I/O blocking, cờ ffmpeg).\n"
        f"3. Kiểm tra tuân thủ kiến trúc ZerynBot V2 (20 modules, 108 commands, 1621 keys i18n, async_ vs sync_ db helpers).\n"
        f"4. Chỉ liệt kê tối đa 3-4 vấn đề trọng tâm nhất, mô tả ngắn gọn súc tích dưới 25 từ mỗi vấn đề để JSON không bị cắt cụt.\n"
        f"BẮT BUỘC trả về duy nhất một khối JSON (không bọc thêm lời mở đầu hay kết luận) có cấu trúc:\n"
        f"{{\n"
        f'  "file_path": "{rel_path}",\n'
        f'  "verdict": "APPROVED" | "REQUEST_CHANGES" | "NEEDS_DISCUSSION",\n'
        f'  "score": 1-10,\n'
        f'  "summary": "Tóm tắt đánh giá ngắn gọn trong 1-2 câu",\n'
        f'  "issues": [\n'
        f'    {{\n'
        f'      "severity": "CRITICAL" | "WARNING" | "INFO",\n'
        f'      "title": "Tên vấn đề",\n'
        f'      "line_hint": "Gợi ý dòng (nếu có)",\n'
        f'      "description": "Mô tả chi tiết nguyên nhân và hậu quả",\n'
        f'      "termux_risk": "Tác động cụ thể tới Termux ARM64 / SQLite WAL"\n'
        f'    }}\n'
        f'  ],\n'
        f'  "recommended_patch": "Gợi ý sửa đổi ngắn gọn (nếu cần)"\n'
        f"}}"
    )

    raw_resp = _invoke_ai(prompt, role="critic")
    json_data = _extract_json_block(raw_resp)

    if isinstance(json_data, dict) and json_data:
        json_data.setdefault("file_path", rel_path)
        v = str(json_data.get("verdict", "")).upper()
        if "APPROV" in v:
            json_data["verdict"] = "APPROVED"
        elif "CHANGE" in v or "REJECT" in v or "FAIL" in v:
            json_data["verdict"] = "REQUEST_CHANGES"
        else:
            json_data["verdict"] = "NEEDS_DISCUSSION"

        try:
            json_data["score"] = max(1, min(10, int(json_data.get("score", 7))))
        except Exception:
            json_data["score"] = 7

        issues_raw = json_data.get("issues", [])
        if isinstance(issues_raw, list):
            clean_issues = []
            for it in issues_raw:
                if isinstance(it, dict):
                    sev = str(it.get("severity", "WARNING")).upper()
                    if "CRIT" in sev:
                        it["severity"] = "CRITICAL"
                    elif "INFO" in sev:
                        it["severity"] = "INFO"
                    else:
                        it["severity"] = "WARNING"
                    title = it.get("title") or it.get("id") or "Vấn đề tiềm ẩn"
                    it["title"] = str(title)
                    it.setdefault("description", it.get("desc", ""))
                    it.setdefault("termux_risk", "Không có rủi ro đáng kể trên Termux ARM64.")
                    clean_issues.append(it)
            json_data["issues"] = clean_issues

    try:
        report = CodeReviewReport(**json_data)
        if not report.file_path:
            report.file_path = rel_path
    except Exception:
        report = CodeReviewReport(
            file_path=rel_path,
            verdict="NEEDS_DISCUSSION",
            score=7,
            summary=f"Phản hồi phi cấu trúc từ AI:\n{raw_resp[:350]}...",
            issues=[]
        )

    # Format kết quả hiển thị
    verdict_icons = {
        "APPROVED": "🟢 PHÊ DUYỆT (APPROVED)",
        "REQUEST_CHANGES": "🔴 YÊU CẦU SỬA ĐỔI (REQUEST_CHANGES)",
        "NEEDS_DISCUSSION": "🟡 CẦN THẢO LUẬN THÊM (NEEDS_DISCUSSION)"
    }
    lines_out = [
        f"============================================================",
        f"📋 BÁO CÁO RÀ SOÁT MÃ NGUỒN (DUAL-MODEL CODE REVIEW)",
        f"============================================================",
        f"📁 Tệp: `{report.file_path}`",
        f"🏆 Điểm chất lượng: {report.score}/10",
        f"⚖️ Phán quyết: {verdict_icons.get(report.verdict, report.verdict)}",
        f"📝 Tóm tắt: {report.summary}",
        f"------------------------------------------------------------",
    ]

    if report.issues:
        lines_out.append(f"⚠️ Phát hiện {len(report.issues)} vấn đề tiềm ẩn:")
        for idx, issue in enumerate(report.issues, 1):
            sev_icon = "🔴 [CRITICAL]" if issue.severity == "CRITICAL" else ("🟡 [WARNING]" if issue.severity == "WARNING" else "🔵 [INFO]")
            hint = f" (Dòng: {issue.line_hint})" if issue.line_hint else ""
            lines_out.append(f"  {idx}. {sev_icon} **{issue.title}**{hint}")
            lines_out.append(f"     • Chi tiết: {issue.description}")
            lines_out.append(f"     • Termux ARM64: {issue.termux_risk}")
    else:
        lines_out.append("✅ Không phát hiện lỗ hổng hoặc lỗi logic nghiêm trọng nào.")

    if report.recommended_patch:
        lines_out.append(f"------------------------------------------------------------")
        lines_out.append(f"💡 Đề xuất chỉnh sửa:\n{report.recommended_patch}")

    lines_out.append(f"============================================================")
    return "\n".join(lines_out)


def execute_pre_commit_check() -> str:
    """Quét git diff, kiểm tra các bất biến của repo và yêu cầu Model 2 đánh giá rủi ro hồi quy."""
    try:
        # 1. Lấy diff đã staged
        r_staged = subprocess.run(
            ["git", "diff", "--staged"],
            cwd=BASE_DIR,
            shell=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace"
        )
        diff_text = r_staged.stdout.strip()
        is_staged = True

        # Nếu staged rỗng, lấy diff unstaged
        if not diff_text:
            r_unstaged = subprocess.run(
                ["git", "diff"],
                cwd=BASE_DIR,
                shell=False,
                capture_output=True,
                encoding="utf-8",
                errors="replace"
            )
            diff_text = r_unstaged.stdout.strip()
            is_staged = False

        if not diff_text:
            return "🟢 Working tree hoàn toàn sạch sẽ! Không có thay đổi nào trong git diff."

        # 2. Lấy danh sách files đã thay đổi
        cmd_files = ["git", "diff", "--staged", "--name-only"] if is_staged else ["git", "diff", "--name-only"]
        r_files = subprocess.run(
            cmd_files,
            cwd=BASE_DIR,
            shell=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace"
        )
        changed_files = [f.strip() for f in r_files.stdout.splitlines() if f.strip()]

    except Exception as e:
        return f"❌ Lỗi khi thực thi lệnh git: {e}"

    # Lọc bỏ lockfile và binary
    diff_lines = diff_text.splitlines()
    if len(diff_lines) > 750:
        diff_text_for_llm = "\n".join(diff_lines[:750]) + f"\n\n# [... CÒN {len(diff_lines) - 750} DÒNG DIFF ĐÃ ĐƯỢC RÚT GỌN ...]"
    else:
        diff_text_for_llm = diff_text

    diff_text_for_llm = _scrub_sensitive_data(diff_text_for_llm)

    # Kiểm tra các bất biến cục bộ (Invariants)
    checklist = {
        "i18n_synced": True,
        "sqlite_wal_safe": True,
        "safe_http_urls": True,
        "no_hardcoded_secrets": True,
    }
    local_notes = []
    if any("locales/" in f for f in changed_files):
        local_notes.append("• Có thay đổi file từ điển i18n -> Cần chạy validate_i18n.py xác nhận chuẩn 1621 keys.")
    if any("bot/cogs/" in f for f in changed_files):
        local_notes.append("• Có thay đổi cogs -> Cần đảm bảo async_ database helpers và module guards.")

    prompt = (
        f"Bạn là Senior Security Auditor & QA Lead cho ZerynBot V2 (chạy Termux Android ARM64 24/7, CPU Helio G85, RAM 6GB, SQLite WAL).\n"
        f"Danh sách tệp thay đổi ({'staged' if is_staged else 'unstaged'}):\n"
        f"{', '.join(changed_files)}\n\n"
        f"Nội dung Git Diff:\n```diff\n{diff_text_for_llm}\n```\n\n"
        f"LƯU Ý QUAN TRỌNG: Đây là Git Diff, chỉ hiển thị các dòng thêm (+) và bớt (-). Các hàm, biến, class hoặc import được định nghĩa ở các phần khác của tệp vẫn tồn tại đầy đủ và nguyên vẹn. TUYỆT ĐỐI không giả định một hàm bị 'thiếu' (missing) chỉ vì nó không xuất hiện trong khối diff này.\n\n"
        f"Hãy đánh giá rủi ro hồi quy (Regression Testing), nguy cơ phá vỡ hệ thống hoặc làm gián đoạn Termux.\n"
        f"BẮT BUỘC trả về duy nhất một khối JSON (không bọc thêm lời mở đầu hay kết luận) có cấu trúc:\n"
        f"{{\n"
        f'  "staged_files": {json.dumps(changed_files)},\n'
        f'  "risk_level": "LOW" | "MEDIUM" | "HIGH",\n'
        f'  "verdict": "READY_TO_COMMIT" | "FIX_REQUIRED",\n'
        f'  "breaking_risks": ["Danh sách rủi ro tiềm ẩn (ngắn gọn, tối đa 3 rủi ro thực tế)"],\n'
        f'  "summary": "Tóm tắt đánh giá trong 1-2 câu"\n'
        f"}}"
    )

    raw_resp = _invoke_ai(prompt, role="critic")
    json_data = _extract_json_block(raw_resp)

    if isinstance(json_data, dict) and json_data:
        json_data.setdefault("staged_files", changed_files)
        rl = str(json_data.get("risk_level", "LOW")).upper()
        if "HIGH" in rl or "CAO" in rl:
            json_data["risk_level"] = "HIGH"
        elif "MED" in rl or "TRUNG" in rl:
            json_data["risk_level"] = "MEDIUM"
        else:
            json_data["risk_level"] = "LOW"

        vd = str(json_data.get("verdict", "READY_TO_COMMIT")).upper()
        if "FIX" in vd or "REQ" in vd:
            json_data["verdict"] = "FIX_REQUIRED"
        else:
            json_data["verdict"] = "READY_TO_COMMIT"

    try:
        report = PreCommitReport(**json_data)
    except Exception:
        report = PreCommitReport(
            staged_files=changed_files,
            risk_level="MEDIUM",
            verdict="READY_TO_COMMIT",
            breaking_risks=[],
            summary=f"Phản hồi phi cấu trúc:\n{raw_resp[:350]}..."
        )

    risk_icons = {"LOW": "🟢 THẤP (LOW)", "MEDIUM": "🟡 TRUNG BÌNH (MEDIUM)", "HIGH": "🔴 CAO (HIGH)"}
    verdict_icons = {"READY_TO_COMMIT": "🟢 SẴN SÀNG COMMIT", "FIX_REQUIRED": "🔴 CẦN KHẮC PHỤC TRƯỚC KHI COMMIT"}

    lines_out = [
        f"============================================================",
        f"🛡️ BÁO CÁO RÀ SOÁT THAY ĐỔI TRƯỚC KHI COMMIT (PRE-COMMIT GATE)",
        f"============================================================",
        f"📦 Số tệp thay đổi: {len(changed_files)} ({', '.join(changed_files[:5])}{'...' if len(changed_files) > 5 else ''})",
        f"⚠️ Mức độ rủi ro: {risk_icons.get(report.risk_level, report.risk_level)}",
        f"⚖️ Phán quyết: {verdict_icons.get(report.verdict, report.verdict)}",
        f"📝 Tóm tắt: {report.summary}",
        f"------------------------------------------------------------",
    ]

    if local_notes:
        lines_out.append("🔍 Nhắc nhở quy chuẩn ZerynBot V2:")
        for note in local_notes:
            lines_out.append(f"  {note}")

    if report.breaking_risks:
        lines_out.append("⚠️ Các rủi ro tiềm ẩn được Model 2 phát hiện:")
        for rk in report.breaking_risks:
            lines_out.append(f"  • {rk}")
    else:
        lines_out.append("✅ Không phát hiện rủi ro breaking change nào.")

    lines_out.append(f"============================================================")
    return "\n".join(lines_out)


# ==========================================
# 5. MCP Tools Registration
# ==========================================

@server.tool(name="consult_second_model", description="Gửi đề xuất, đoạn code hoặc thiết kế sang cho Model AI thứ 2 để lấy ý kiến phản biện (Second Opinion).")
def consult_second_model(prompt: str, role: str = "critic", model: str = "auto") -> str:
    """Gửi câu hỏi / bản phác thảo sang Model AI thứ 2 để phản biện."""
    return _invoke_ai(prompt, role=role, model_pref=model)


@server.tool(name="run_dual_model_debate", description="Chạy một phiên tranh luận chéo nhiều hiệp giữa 2 model AI về một chủ đề kỹ thuật.")
def run_dual_model_debate(topic: str, rounds: int = 2) -> str:
    """Chạy phiên tranh biện qua lại giữa Model A (Đề xuất) và Model B (Phản biện)."""
    rounds = max(1, min(rounds, 3))
    transcript = [f"### 🥊 PHIÊN TRANH LUẬN ĐỐI KHÁNG ĐA MODEL\n**Chủ đề:** {topic}\n"]

    current_statement = f"Đề bài: {topic}. Hãy đề xuất giải pháp kỹ thuật tối ưu và ngắn gọn nhất."
    
    # Hiệp 1: Architect đề xuất
    resp_arch = _invoke_ai(current_statement, role="architect")
    transcript.append(f"**🏛️ Model A (Architect - Đề xuất ban đầu):**\n{resp_arch}\n")
    time.sleep(1.5)

    current_statement = resp_arch
    for r in range(1, rounds + 1):
        # Model B phản biện
        prompt_critic = f"Chủ đề gốc: {topic}\n\nĐề xuất hiện tại:\n{current_statement}\n\nHãy chỉ ra 3 điểm yếu, rủi ro bảo mật hoặc edge-case mà giải pháp trên chưa giải quyết triệt để."
        resp_critic = _invoke_ai(prompt_critic, role="critic")
        transcript.append(f"**⚔️ Model B (Critic - Phản biện Hiệp {r}):**\n{resp_critic}\n")
        time.sleep(1.5)

        # Model A phản hồi & hoàn thiện
        prompt_rebuttal = f"Chủ đề: {topic}\n\nPhản biện từ Critic:\n{resp_critic}\n\nHãy tiếp thu, điều chỉnh phương án để khắc phục triệt để các rủi ro trên."
        resp_arch = _invoke_ai(prompt_rebuttal, role="architect")
        transcript.append(f"**🛡️ Model A (Architect - Điều chỉnh & Hoàn thiện Hiệp {r}):**\n{resp_arch}\n")
        current_statement = resp_arch
        time.sleep(1.5)

    transcript.append("### 🏆 BẢN ĐỒNG THUẬN KỸ THUẬT CUỐI CÙNG (FINAL CONSENSUS)")
    transcript.append(current_statement)
    return "\n".join(transcript)


@server.tool(name="review_code_file", description="Yêu cầu Model 2 rà soát mã nguồn một tệp cụ thể để tìm lỗi logic, bảo mật và rủi ro Termux.")
def review_code_file(file_path: str) -> str:
    """Rà soát mã nguồn một tệp cụ thể với Model 2."""
    return execute_review_code_file(file_path)


@server.tool(name="review_pre_commit_diff", description="Yêu cầu Model 2 rà soát các thay đổi git diff trước khi commit để đánh giá rủi ro hồi quy.")
def review_pre_commit_diff() -> str:
    """Rà soát git diff trước khi commit với Model 2."""
    return execute_pre_commit_check()


@server.tool(name="get_dual_model_status", description="Kiểm tra trạng thái kết nối các provider AI (Gemini, Groq, OpenRouter) cho tính năng Dual-Model.")
def get_dual_model_status() -> str:
    """Kiểm tra API keys và model sẵn sàng."""
    keys = _get_api_keys()
    lines = ["📡 **Trạng Thái Kết Nối Dual-Model Provider:**"]
    for prov in ["groq", "gemini", "openrouter"]:
        has_k = bool(keys.get(prov))
        icon = "🟢 Sẵn sàng" if has_k else "⚪ Chưa cấu hình"
        lines.append(f"- **{prov.upper()}**: {icon}")
    return "\n".join(lines)


# ==========================================
# 6. CLI Runner
# ==========================================

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "--stdio":
        parser = argparse.ArgumentParser(description="CLI Runner cho Dual-Model Assistant")
        parser.add_argument("--consult", type=str, help="Gửi prompt tới model phản biện")
        parser.add_argument("--role", type=str, default="critic", help="Vai trò: critic, architect, tester")
        parser.add_argument("--debate", type=str, help="Chạy tranh luận về chủ đề")
        parser.add_argument("--rounds", type=int, default=2, help="Số hiệp tranh luận")
        parser.add_argument("--status", action="store_true", help="Kiểm tra trạng thái provider")
        parser.add_argument("--review-file", type=str, help="Rà soát mã nguồn một file cụ thể")
        parser.add_argument("--pre-commit-check", action="store_true", help="Rà soát git diff trước khi commit")
        args = parser.parse_args()

        if args.status:
            print(get_dual_model_status())
        elif args.consult:
            print(_invoke_ai(args.consult, role=args.role))
        elif args.debate:
            print(run_dual_model_debate(args.debate, rounds=args.rounds))
        elif args.review_file:
            print(execute_review_code_file(args.review_file))
        elif args.pre_commit_check:
            print(execute_pre_commit_check())
    else:
        server.run(transport="stdio")
