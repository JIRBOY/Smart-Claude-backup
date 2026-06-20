# Smart Claude Code Backup — usage notes

## First-run flow

```
$ python scripts/backup.py
Detected candidate Claude Code folders:
  [1] /home/user/.claude
  [2] /home/user/.config/claude
  [m] enter a custom path
Pick [1-2/m]: 1
=== Smart Claude Code Backup Manifest ===
  Source       : /home/user/.claude
  Destination  : .../Smart-Claude-backup/backups
  Format       : zip
  Excludes     : node_modules, __pycache__, .venv, ...
  Status       : CHANGED since last backup
=========================================
Proceed? [y]es / [e]dit / [n]o:
```

## Edit mode

- Empty input keeps the current value.
- `excludes` accepts three styles:
  - bare list — replaces the whole list, e.g. `node_modules,*.log,cache`
  - `+a,b`    — appends entries
  - `-a,b`    — removes entries

## Auto-backup on no-change

The script SHA-256-hashes the (filtered) tree. If the hash matches
`last_hash` in `backup_config.json`, the prompt is skipped and a fresh
archive is still written (so you always get a timestamped snapshot).
Force the prompt with `--force-prompt`.

## Formats

- `zip` — default, portable, deflated.
- `tar.gz` — better on POSIX trees with symlinks/permissions.
- `copy` — plain directory mirror (useful as a working snapshot).

## Common overrides

```bash
# one-off backup of a project's local .claude folder
python scripts/backup.py --source ./.claude --dest /mnt/usb/claude --format tar.gz --yes

# wipe remembered settings
python scripts/backup.py --reset

# always show the manifest, even when unchanged
python scripts/backup.py --force-prompt
```

## Windows notes

- Run from PowerShell: `python .\scripts\backup.py`.
- Detected paths include `%APPDATA%\Claude` and `%APPDATA%\claude-code`.
- Use forward or backslashes interchangeably; `Path.expanduser()` handles both.

## Recovery

- `zip` / `tar.gz` archives extract with standard tools.
- `copy` archives are plain folders — restore by copying back onto the
  source path (stop Claude Code first).

## Where state lives

- `scripts/backup_config.json` — source / destination / format / excludes / last hash / last backup time.
- Delete it (or run `--reset`) to start fresh.
