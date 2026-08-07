---
name: zerynbot_architecture_context
description: >
  Use ARCHITECTURE.md as the primary context for all work on ZerynBot V2.
  Read it first before touching any code. Update it whenever the codebase changes
  so it stays accurate as the single source of truth for AI assistants.
---

# Skill: ZerynBot V2 — Architecture-First Context

## Purpose
This skill instructs the AI to:
1. **Always read `ARCHITECTURE.md` first** before writing, editing, or debugging any code in this project.
2. **Treat `ARCHITECTURE.md` as the single source of truth** — avoid scanning raw code files for context that is already documented there.
3. **Keep `ARCHITECTURE.md` up to date** whenever a structural change is made (new cog, new DB table, new locale key pattern, new gotcha discovered, etc.).

---

## Step 1: Read Architecture Before Coding

At the start of every task involving ZerynBot V2, you MUST read:

```
d:\Project\Discord Bots\v2\ARCHITECTURE.md
```

Use it to understand:
- The **tech stack** and component roles (Section 1)
- The **directory structure** and what each file does (Section 2)
- The **database schema** — which table to read/write for a given feature (Section 3)
- The **i18n engine usage** — how to call `tr()` and `t()` correctly (Section 4)
- The **cog responsibilities** — which cog owns a given feature (Section 5)
- The **dashboard architecture** — how Flask routes and templates are connected (Section 6)
- The **data flow diagrams** for Automod and multi-language command flows (Section 7)
- The **ARM optimization rules** (Section 8)
- The **mandatory development rules** — async/sync separation, module guards, cache invalidation (Section 9)
- The **known gotchas and anti-patterns** to avoid (Section 10)

> **Do NOT scan raw cog files, database.py, or dashboard templates for context if the answer is already in ARCHITECTURE.md.**

---

## Step 2: Identify What Changed (Triggers to Update ARCHITECTURE.md)

After completing any task, check if any of the following changed:

| Trigger | ARCHITECTURE.md Section to Update |
|---------|-----------------------------------|
| New cog file added or removed | Section 2 (file map) + Section 5 (cog table) |
| New database table created | Section 3 (schema table) |
| New column added to existing table | Section 3 (update that row's "Key Columns") |
| New locale key namespace added | Section 4 (i18n usage patterns) |
| New module name added to `DEFAULT_MODULES` | Section 3 (`guild_modules` row, module list) |
| New bug discovered and fixed (race condition, JS error, etc.) | Section 10 (add a new row to gotchas table) |
| New mandatory development rule established | Section 9 (add new numbered rule) |
| New Flask route category added | Section 6 (dashboard architecture) |
| ARM optimization technique discovered | Section 8 |
| Locale count changes (e.g. 856 → 860 keys) | Section 2 (locales file map) |

---

## Step 3: How to Update ARCHITECTURE.md

When updating, follow these rules:

1. **Edit only the sections that changed.** Do not rewrite the entire file.
2. **Keep the numbered section structure** (`## 1.`, `## 2.`, ...) intact.
3. **Add new gotchas** to Section 10 as new rows in the table — do not edit existing rows unless they are factually wrong.
4. **Update the locale key count** in Section 2 under `locales/` when keys are added/removed. Current count: **856 keys per file**.
5. **Commit `ARCHITECTURE.md` together with the code change** that triggered the update so the git history stays coherent.

### Template: Adding a New Gotcha Row
```markdown
| 10 | Doing X in Y context | Always do Z instead |
```

### Template: Adding a New Database Table Row
```markdown
| `new_table_name` | `primary_key_col` | Purpose description and key columns listed here. |
```

### Template: Adding a New Cog to Section 5
```markdown
| **NewCog** | `bot/cogs/newcog.py` | Description of what it listens to and what it does. |
```

---

## Step 4: Commit Message Convention

When updating ARCHITECTURE.md, always include it in the same commit as the related code:

```
git add ARCHITECTURE.md bot/cogs/newcog.py
git commit -m "Add newcog + update ARCHITECTURE.md"
```

If ARCHITECTURE.md is updated alone (e.g. fixing an inaccuracy):
```
git commit -m "Update ARCHITECTURE.md: fix <section> description"
```

---

## Quick Reference: Critical Rules (from ARCHITECTURE.md §9)

| Rule | Summary |
|------|---------|
| i18n | Never hardcode strings — use `tr(settings, "namespace.key")` in bot, `{{ t('key') }}` in templates |
| 6 locales | Add new keys to all 6 JSON files simultaneously |
| Async/Sync | Bot cogs → `async_*` DB functions. Dashboard → sync DB functions. Never mix. |
| Module guard | Every command must check `await async_is_module_enabled(...)` before executing |
| Cache write | After DB write, call `await cache.adelete(f"settings:{guild_id}")` |
| Background loops | Re-query DB state before any mutation inside timed loops |
| JS templates | No duplicate function names in `<script>` blocks; `window.I18N_*` at top-level scope |
