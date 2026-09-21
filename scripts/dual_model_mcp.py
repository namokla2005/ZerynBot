"""
dual_model_mcp.py — Dual-Model Reasoning & Adversarial Debate MCP Server for Antigravity IDE.

Cho phép Antigravity kết nối đồng thời với model AI thứ 2 (Google Gemini, Groq Qwen/GPT-OSS, OpenRouter)
để cùng suy luận, phản biện chéo (Critique), đối chiếu kiến trúc và tranh biện nhiều hiệp (Multi-round Debate).

Hỗ trợ:
  - Chuẩn Model Context Protocol (MCP 2.x) qua Stdio Transport.
  - CLI Direct Invocation (cho phép gọi trực tiếp qua terminal/script).
  - Khả năng tự động xoay vòng model khi gặp Rate Limit (HTTP 429 Auto-Fallback).
"""
import os
import sys
import time
import json
import sqlite3
import argparse
import requests

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
    version="1.1.0",
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "bot.db")

GROQ_FALLBACK_MODELS = [
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "groq/compound-mini",
]


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
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 1024}
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
            "temperature": 0.4,
            "max_tokens": 700
        }
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=30)
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
        "temperature": 0.4,
        "max_tokens": 1024
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
            "Bạn là Senior Security Auditor & Code Reviewer khó tính. "
            "Nhiệm vụ của bạn là soi xét tỉ mỉ mọi giải pháp, chỉ ra các lỗ hổng bảo mật (SSRF, XSS, IDOR, SQL Injection), "
            "vấn đề hiệu năng (ARM64 Termux, nghẽn SQLite WAL), race conditions, lỗi logic và các trường hợp biên (edge cases). "
            "Trả lời súc tích bằng tiếng Việt, đi thẳng vào các điểm yếu cốt lõi bằng gạch đầu dòng ngắn gọn (dưới 400 từ)."
        ),
        "architect": (
            "Bạn là Principal Software Architect. "
            "Nhiệm vụ của bạn là đưa ra giải pháp kiến trúc sạch, chuẩn mực, tuân thủ Clean Architecture và tối ưu hóa tài nguyên. "
            "Trả lời súc tích bằng tiếng Việt, nêu rõ ưu điểm và các bước then chốt (dưới 400 từ)."
        ),
        "tester": (
            "Bạn là QA Automation Lead chuyên kiểm thử phá hoại (Adversarial Testing). "
            "Hãy đặt ra các kịch bản thử nghiệm khắc nghiệt nhất, input dị thường và tình huống crash để kiểm chứng hệ thống. "
            "Trả lời bằng tiếng Việt, gạch đầu dòng ngắn gọn (dưới 400 từ)."
        ),
        "general": (
            "Bạn là AI Co-Reasoning Partner chuyên nghiệp. "
            "Hãy tham gia trao đổi, suy luận logic và đưa ra góc nhìn độc lập, khách quan về vấn đề được đặt ra."
        )
    }
    sys_inst = role_instructions.get(role, role_instructions["general"])

    # 1. Nếu chỉ định rõ Gemini hoặc có Gemini key
    if (model_pref.startswith("gemini") or model_pref == "auto") and keys["gemini"]:
        model = model_pref if model_pref.startswith("gemini") else "gemini-2.0-flash"
        return _call_gemini(keys["gemini"], model, prompt, sys_inst)

    # 2. Nếu có Groq key (mặc định cực nhanh, lý tưởng cho phản biện)
    if keys["groq"]:
        model = "qwen/qwen3.8-27b" if model_pref == "auto" else model_pref
        if not model.startswith("qwen") and not model.startswith("openai/gpt-oss") and not model.startswith("groq/"):
            model = "qwen/qwen3.8-27b"
        return _call_groq(keys["groq"], model, prompt, sys_inst)

    # 3. Fallback OpenRouter
    if keys["openrouter"]:
        model = "deepseek/deepseek-chat" if model_pref == "auto" else model_pref
        return _call_openrouter(keys["openrouter"], model, prompt, sys_inst)

    return (
        "❌ Chưa tìm thấy API Key nào (Gemini, Groq hoặc OpenRouter). "
        "Vui lòng cấu hình GEMINI_API_KEY hoặc GROQ_API_KEY trong file .env hoặc trên Web Dashboard /admin!"
    )


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


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "--stdio":
        parser = argparse.ArgumentParser(description="CLI Runner cho Dual-Model Assistant")
        parser.add_argument("--consult", type=str, help="Gửi prompt tới model phản biện")
        parser.add_argument("--role", type=str, default="critic", help="Vai trò: critic, architect, tester")
        parser.add_argument("--debate", type=str, help="Chạy tranh luận về chủ đề")
        parser.add_argument("--rounds", type=int, default=2, help="Số hiệp tranh luận")
        parser.add_argument("--status", action="store_true", help="Kiểm tra trạng thái provider")
        args = parser.parse_args()

        if args.status:
            print(get_dual_model_status())
        elif args.consult:
            print(_invoke_ai(args.consult, role=args.role))
        elif args.debate:
            print(run_dual_model_debate(args.debate, rounds=args.rounds))
    else:
        server.run(transport="stdio")
