# Agent Configuration for ZerynBot V2

## Workspace Skills
All skills in `.agents/skills/` are auto-discovered.

## Primary Context Document
`ARCHITECTURE.md` in the project root is the single source of truth.
AI assistants should read it before writing any code.

## Key Conventions
- Bot: Python (discord.py), async DB, tr() for i18n
- Dashboard: Flask, Jinja2, sync DB, t() in templates
- Locales: 6 files (vi/en/zh/es/pt/fr), must stay in sync at all times
- Database: SQLite WAL mode at data/bot.db
