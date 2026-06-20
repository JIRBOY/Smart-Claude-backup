---
name: smart-claude-backup
description: "Smart-backup Claude Code CLI config: locate, confirm, remember source folder; exclude temp/deps; pick archive format and destination; manifest-confirm each run."
---

# Smart Claude Code CLI Backup

Use when the user asks to back up, snapshot, archive, or migrate Claude Code CLI configuration (`~/.claude`, `~/.config/claude`, `%APPDATA%\Claude`, or a project `.claude/` folder). Driven by `scripts/backup.py`; settings persist in `scripts/backup_config.json`.

## Workflow

1. `python scripts/backup.py` from the `Smart-Claude-backup/` folder (or pass `--config-dir`).
2. First run: script auto-discovers candidate Claude Code config folders, asks the user to confirm or override, then remembers the choice.
3. Each run prints a **manifest** (source, destination, format, excludes, last-run hash) and waits for `[y]es / [e]dit / [n]o`.
   - `y`: proceed.
   - `e`: interactively change source, destination, format (`zip` / `tar.gz` / `copy`), or exclude patterns; saved back to config.
   - `n`: abort.
4. Script hashes the resolved file tree. If unchanged since the last successful backup, it auto-confirms and writes a fresh timestamped archive without re-prompting (unless `--force-prompt`).
5. Outputs land in the configured destination as `claude-config-YYYYMMDD-HHMMSS.<ext>`.

## Defaults

- Search order: `$CLAUDE_HOME`, `~/.claude`, `~/.config/claude`, `$APPDATA/Claude`, `./.claude`.
- Excludes: `node_modules`, `__pycache__`, `.venv`, `venv`, `*.log`, `*.tmp`, `*.lock`, `.DS_Store`, `Thumbs.db`, `cache/`, `tmp/`, `logs/`, `*.pyc`.
- Format: `zip` (portable). Switch with `e` or `--format`.
- Destination: `./backups/` under this skill folder.

## CLI flags (optional)

- `--source PATH` override source once without persisting.
- `--dest PATH` override destination once.
- `--format {zip,tar.gz,copy}`.
- `--yes` skip the manifest prompt (still respects no-change auto-backup).
- `--force-prompt` always show manifest even when unchanged.
- `--reset` wipe stored config.

## Files

- `scripts/backup.py` — main entry point.
- `scripts/backup_config.json` — persisted source / dest / format / excludes / last-hash.
- `references/usage.md` — extended examples, recovery tips, Windows notes.

Run `python scripts/backup.py --help` for the live argument list.
