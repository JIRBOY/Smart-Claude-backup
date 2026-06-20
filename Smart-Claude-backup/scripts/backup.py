#!/usr/bin/env python3
"""Smart Claude Backup - Claude Code CLI config backup tool.

Integrates best features from granite, eclipse, helix, falcon models:
- Auto-detect config folder, remember settings
- Exclude temp/dependency files
- Multiple backup formats (zip, tar.gz, copy)
- SHA256 tree-hash change detection
- Backup history (last 20)
- Windows-compatible output (no emoji)
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import sys
import tarfile
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

# ============================================================
# Constants
# ============================================================

SETTINGS_DIR = Path.home() / ".smart-claude-backup"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"
MANIFEST_FILENAME = "backup_manifest.json"

DEFAULT_EXCLUDES = [
    # Temp files
    "*.tmp", "*.temp", "*.swp", "*.swo", "*~",
    ".DS_Store", "Thumbs.db", "desktop.ini",
    # Dependency dirs
    "node_modules", "__pycache__",
    ".venv", "venv", "env", ".env",
    # Cache
    ".cache", "cache", "tmp",
    # Logs
    "*.log", "logs",
    # Build artifacts
    "dist", "build", ".next", ".nuxt",
    ".terraform", ".serverless",
    # Python
    "*.pyc", "*.pyo", "*.pyd",
    # Lock/backup files
    "*.lock", "*.bak", "*.old", "*.crdownload",
    # Binaries
    "*.bin", "*.exe", "*.dll", "*.so", "*.dylib",
    # Git
    ".git",
]

CONFIG_CANDIDATES = [
    "~/.claude",
    "~/.config/claude",
    "~/.config/claude-code",
    "~/Library/Application Support/Claude",
    "~/AppData/Roaming/Claude",
    "~/AppData/Roaming/claude-code",
    "~/AppData/Local/Claude",
    "~/AppData/Local/claude-code",
    "./.claude",
]

VALID_FORMATS = ("zip", "tar.gz", "copy")


# ============================================================
# Config dataclass
# ============================================================

@dataclass
class BackupConfig:
    config_dir: Optional[str] = None
    backup_dir: Optional[str] = None
    backup_format: str = "zip"
    exclude_patterns: List[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDES))
    auto_backup_no_change: bool = True
    last_backup_time: Optional[str] = None
    last_manifest: Optional[Dict] = None
    backup_history: List[Dict] = field(default_factory=list)

    @classmethod
    def load(cls) -> BackupConfig:
        if SETTINGS_FILE.exists():
            try:
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                # Only keep known fields
                known = {k: data.get(k, getattr(cls(), k)) for k in cls.__dataclass_fields__}
                return cls(**known)
            except Exception as e:
                print(f"[warn] Failed reading settings: {e}; using defaults.")
        return cls()

    def save(self) -> None:
        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


# ============================================================
# Utility functions
# ============================================================

def expand_path(path_str: str) -> Path:
    """Expand user directory and environment variables."""
    return Path(os.path.expandvars(os.path.expanduser(path_str))).resolve()


def format_size(size_bytes: int) -> str:
    """Format byte size to human readable."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def file_sha256(filepath: Path) -> str:
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except (IOError, OSError):
        return ""


# ============================================================
# Discovery
# ============================================================

def discover_config_dirs() -> List[Tuple[Path, str]]:
    """Scan for Claude Code config directories."""
    found: List[Tuple[Path, str]] = []
    seen: set = set()

    # Environment variables
    for env_var in ("CLAUDE_CONFIG_DIR", "CLAUDE_HOME"):
        env_path = os.environ.get(env_var)
        if env_path:
            p = expand_path(env_path)
            if p.exists() and p.is_dir() and str(p) not in seen:
                seen.add(str(p))
                found.append((p, f"env {env_var}"))

    # Common locations
    for cand in CONFIG_CANDIDATES:
        p = expand_path(cand)
        if p.exists() and p.is_dir() and str(p) not in seen:
            # Check if it looks like a Claude config dir
            has_files = any(f.is_file() for f in p.iterdir())
            if has_files or "claude" in p.name.lower():
                seen.add(str(p))
                found.append((p, cand))

    return found


def prompt_select_config_dir(found: List[Tuple[Path, str]], current: Optional[str]) -> Optional[Path]:
    """Interactive config directory selection."""
    if current:
        cur_p = expand_path(current)
        if cur_p.exists():
            resp = input(f"Use remembered config folder?\n  {cur_p}\n[Y/n/path] ").strip()
            if resp == "" or resp.lower().startswith("y"):
                return cur_p
            if resp.lower() not in ("n", "no"):
                custom = expand_path(resp)
                if custom.exists() and custom.is_dir():
                    return custom
                print(f"Path not found: {custom}")

    if not found:
        print("No Claude Code config folder auto-detected.")
        manual = input("Enter path: ").strip()
        if not manual:
            return None
        p = expand_path(manual)
        if p.exists() and p.is_dir():
            return p
        print(f"Path does not exist: {p}")
        return None

    print(f"Detected {len(found)} candidate config folder(s):")
    for i, (path, desc) in enumerate(found, 1):
        file_count = sum(1 for _ in path.rglob("*") if _.is_file())
        total_size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        print(f"  [{i}] {path}")
        print(f"      Source: {desc}")
        print(f"      Files: {file_count}, Size: {format_size(total_size)}")
    print("  [m] Enter a custom path")
    print("  [q] Cancel")

    while True:
        ans = input(f"Pick [1-{len(found)}/m/q]: ").strip().lower()
        if ans == "q":
            return None
        if ans == "m":
            custom = input("Custom path: ").strip()
            p = expand_path(custom)
            if p.exists() and p.is_dir():
                return p
            print(f"Path does not exist: {p}")
            continue
        try:
            idx = int(ans) - 1
            if 0 <= idx < len(found):
                return found[idx][0]
        except ValueError:
            pass
        print("Invalid selection.")


# ============================================================
# File scanning & exclusion
# ============================================================

def is_excluded(rel_path: Path, excludes: List[str]) -> bool:
    """Check if a relative path should be excluded."""
    rel_str = str(rel_path).replace("\\", "/")
    name = rel_path.name
    parts = rel_str.split("/")

    for pat in excludes:
        pat = pat.strip()
        if not pat or pat.startswith("#"):
            continue

        # Directory pattern (ends with /)
        if pat.endswith("/"):
            dir_pat = pat.rstrip("/")
            for part in parts:
                if fnmatch.fnmatch(part, dir_pat):
                    return True
            continue

        # Full path match
        if fnmatch.fnmatch(rel_str, pat):
            return True

        # Filename match
        if fnmatch.fnmatch(name, pat):
            return True

        # Any path part match
        for part in parts:
            if fnmatch.fnmatch(part, pat):
                return True

    return False


def iter_files(source: Path, excludes: List[str]) -> Iterable[Path]:
    """Iterate over files in source, skipping excluded paths."""
    for root, dirs, files in os.walk(source):
        root_p = Path(root)
        rel_root = root_p.relative_to(source) if root_p != source else Path()

        # Prune excluded dirs in-place
        dirs[:] = [d for d in dirs if not is_excluded(rel_root / d, excludes)]

        for f in files:
            rel = rel_root / f
            if not is_excluded(rel, excludes):
                yield root_p / f


def scan_source(source: Path, excludes: List[str]) -> Dict[str, Dict]:
    """Scan source directory and return file info dict."""
    files: Dict[str, Dict] = {}
    source = source.resolve()

    for fp in iter_files(source, excludes):
        rel = str(fp.relative_to(source)).replace("\\", "/")
        try:
            stat = fp.stat()
            files[rel] = {
                "size": stat.st_size,
                "hash": file_sha256(fp),
            }
        except (OSError, PermissionError) as e:
            print(f"  Skipped {rel}: {e}")

    return files


# ============================================================
# Change detection
# ============================================================

def compute_tree_hash(files: Dict[str, Dict]) -> str:
    """Compute SHA256 hash of entire file tree (paths + content hashes)."""
    h = hashlib.sha256()
    for rel_path in sorted(files.keys()):
        h.update(rel_path.encode("utf-8"))
        h.update(b"\0")
        h.update(files[rel_path]["hash"].encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def detect_changes(current: Dict[str, Dict], last: Optional[Dict]) -> Dict:
    """Detect changes between current and last backup."""
    if not last:
        return {
            "added": sorted(current.keys()),
            "removed": [],
            "modified": [],
            "unchanged": [],
            "has_changes": True,
        }

    current_set = set(current.keys())
    last_set = set(last.keys())

    added = sorted(current_set - last_set)
    removed = sorted(last_set - current_set)
    modified = []
    unchanged = []

    for path in sorted(current_set & last_set):
        if current[path]["hash"] != last[path].get("hash"):
            modified.append(path)
        else:
            unchanged.append(path)

    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "unchanged": unchanged,
        "has_changes": bool(added or removed or modified),
    }


# ============================================================
# Backup execution
# ============================================================

def create_backup(
    source: Path,
    files: Dict[str, Dict],
    backup_dir: Path,
    fmt: str,
) -> Tuple[Path, Path]:
    """Create backup archive. Returns (backup_path, manifest_path)."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"claude-config-backup_{timestamp}"

    # Build manifest
    manifest = {
        "version": "2.0",
        "created_at": datetime.now().isoformat(),
        "source_dir": str(source),
        "file_count": len(files),
        "total_size": sum(f["size"] for f in files.values()),
        "tree_hash": compute_tree_hash(files),
        "files": [
            {"path": rel, "size": info["size"], "hash": info["hash"]}
            for rel, info in sorted(files.items())
        ],
    }

    if fmt == "copy":
        out = backup_dir / base_name
        out.mkdir(parents=True, exist_ok=True)
        for rel_path in sorted(files.keys()):
            src = source / rel_path
            dst = out / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        manifest_path = out / MANIFEST_FILENAME
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

    elif fmt == "tar.gz":
        out = backup_dir / f"{base_name}.tar.gz"
        manifest_path = backup_dir / f"{base_name}_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        with tarfile.open(out, "w:gz") as tf:
            for rel_path in sorted(files.keys()):
                tf.add(source / rel_path, arcname=rel_path)
            tf.add(manifest_path, arcname=MANIFEST_FILENAME)

    else:  # zip
        out = backup_dir / f"{base_name}.zip"
        manifest_path = backup_dir / f"{base_name}_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel_path in sorted(files.keys()):
                zf.write(source / rel_path, arcname=rel_path)
            zf.write(manifest_path, arcname=MANIFEST_FILENAME)

    return out, manifest_path


# ============================================================
# Manifest & confirmation
# ============================================================

def print_manifest(
    source: Path,
    backup_dir: Path,
    fmt: str,
    files: Dict[str, Dict],
    changes: Dict,
    current_hash: str,
    last_hash: Optional[str],
):
    """Print backup manifest."""
    total_size = sum(f["size"] for f in files.values())

    print("\n" + "=" * 60)
    print("  BACKUP MANIFEST")
    print("=" * 60)
    print(f"\n  Source      : {source}")
    print(f"  Destination : {backup_dir}")
    print(f"  Format      : {fmt}")
    print(f"  Files       : {len(files)}")
    print(f"  Total size  : {format_size(total_size)}")
    print(f"  Tree hash   : {current_hash[:16]}...")
    print(f"  Last hash   : {(last_hash or '(none)')[:16]}...")

    if changes:
        status = "CHANGED" if changes["has_changes"] else "UNCHANGED"
        print(f"\n  Status      : {status} since last backup")
        print(f"    Added     : {len(changes['added'])}")
        print(f"    Removed   : {len(changes['removed'])}")
        print(f"    Modified  : {len(changes['modified'])}")
        print(f"    Unchanged : {len(changes['unchanged'])}")

        if changes["added"]:
            print(f"\n  [+] Added files ({len(changes['added'])}):")
            for f in changes["added"][:10]:
                print(f"      + {f} ({format_size(files[f]['size'])})")
            if len(changes["added"]) > 10:
                print(f"      ... and {len(changes['added']) - 10} more")

        if changes["modified"]:
            print(f"\n  [~] Modified files ({len(changes['modified'])}):")
            for f in changes["modified"][:10]:
                print(f"      ~ {f} ({format_size(files[f]['size'])})")
            if len(changes["modified"]) > 10:
                print(f"      ... and {len(changes['modified']) - 10} more")

        if changes["removed"]:
            print(f"\n  [-] Removed files ({len(changes['removed'])}):")
            for f in changes["removed"][:10]:
                print(f"      - {f}")
            if len(changes["removed"]) > 10:
                print(f"      ... and {len(changes['removed']) - 10} more")

    print("\n" + "=" * 60)


def interactive_confirm(changes: Dict, cfg: BackupConfig) -> bool:
    """Ask user to confirm backup."""
    if not changes["has_changes"] and cfg.auto_backup_no_change:
        print("\n  No changes detected. Auto-confirming backup...")
        return True

    while True:
        prompt = "Proceed? [Y/n] (e=edit settings, l=list files): "
        if not changes["has_changes"]:
            prompt = "Proceed? [Y/n]: "

        try:
            ans = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return False

        if ans in ("y", "yes", ""):
            return True
        if ans in ("n", "no", "q", "quit"):
            return False
        if ans == "e":
            return False  # Caller will handle edit
        if ans == "l":
            return False  # Caller will handle list
        print("  Invalid input. Please enter y/n/e/l.")


# ============================================================
# Settings editing
# ============================================================

def edit_settings(cfg: BackupConfig) -> BackupConfig:
    """Interactive settings editor."""
    while True:
        print("\n--- Edit Settings ---")
        print(f"  [1] Config dir  : {cfg.config_dir or '(not set)'}")
        print(f"  [2] Backup dir  : {cfg.backup_dir or '(not set)'}")
        print(f"  [3] Format      : {cfg.backup_format}")
        print(f"  [4] Excludes    : {len(cfg.exclude_patterns)} rules")
        print(f"  [5] Auto-backup : {'ON' if cfg.auto_backup_no_change else 'OFF'}")
        print(f"  [0] Done")
        print("-" * 40)

        try:
            choice = input("Select [0-5]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if choice == "1":
            found = discover_config_dirs()
            new = prompt_select_config_dir(found, None)
            if new:
                cfg.config_dir = str(new)
                cfg.save()
                print(f"  Updated: {new}")

        elif choice == "2":
            current = cfg.backup_dir or str(Path.home() / "claude_backups")
            new = input(f"  Backup dir [{current}]: ").strip()
            if new:
                p = expand_path(new)
                p.mkdir(parents=True, exist_ok=True)
                cfg.backup_dir = str(p)
                cfg.save()
                print(f"  Updated: {p}")

        elif choice == "3":
            print(f"  Formats: {VALID_FORMATS}")
            new = input(f"  Format [{cfg.backup_format}]: ").strip()
            if new in VALID_FORMATS:
                cfg.backup_format = new
                cfg.save()
                print(f"  Updated: {new}")
            elif new:
                print("  Invalid format.")

        elif choice == "4":
            manage_excludes(cfg)

        elif choice == "5":
            cfg.auto_backup_no_change = not cfg.auto_backup_no_change
            cfg.save()
            print(f"  Auto-backup: {'ON' if cfg.auto_backup_no_change else 'OFF'}")

        elif choice == "0":
            break

    return cfg


def manage_excludes(cfg: BackupConfig):
    """Manage exclusion patterns."""
    patterns = cfg.exclude_patterns

    while True:
        print(f"\n--- Exclusion Rules ({len(patterns)} total) ---")
        for i, p in enumerate(patterns[:20], 1):
            print(f"  {i:2}. {p}")
        if len(patterns) > 20:
            print(f"  ... and {len(patterns) - 20} more")

        print("\n  [a] Add rule")
        print("  [d] Delete by number")
        print("  [+] Append multiple (comma-separated)")
        print("  [-] Remove multiple (comma-separated)")
        print("  [r] Reset to defaults")
        print("  [0] Back")

        try:
            action = input("  Action: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if action == "a":
            new_pat = input("  New rule: ").strip()
            if new_pat and new_pat not in patterns:
                patterns.append(new_pat)
                cfg.save()
                print(f"  Added: {new_pat}")

        elif action == "d":
            idx_str = input("  Number to delete: ").strip()
            if idx_str.isdigit():
                idx = int(idx_str) - 1
                if 0 <= idx < len(patterns):
                    removed = patterns.pop(idx)
                    cfg.save()
                    print(f"  Removed: {removed}")

        elif action.startswith("+"):
            to_add = action[1:] if action != "+" else input("  Rules to add: ").strip()
            for tok in to_add.split(","):
                tok = tok.strip()
                if tok and tok not in patterns:
                    patterns.append(tok)
            cfg.save()
            print(f"  Added {len([t for t in to_add.split(',') if t.strip()])} rule(s).")

        elif action.startswith("-"):
            to_rem = action[1:] if action != "-" else input("  Rules to remove: ").strip()
            removed = []
            for tok in to_rem.split(","):
                tok = tok.strip()
                if tok in patterns:
                    patterns.remove(tok)
                    removed.append(tok)
            cfg.save()
            print(f"  Removed {len(removed)} rule(s).")

        elif action == "r":
            cfg.exclude_patterns = list(DEFAULT_EXCLUDES)
            cfg.save()
            print(f"  Reset to {len(DEFAULT_EXCLUDES)} default rules.")

        elif action == "0":
            break


# ============================================================
# Status display
# ============================================================

def show_status(cfg: BackupConfig):
    """Display current settings and backup history."""
    print("\n" + "=" * 60)
    print("  SMART CLAUDE BACKUP STATUS")
    print("=" * 60)

    print(f"\n  Config dir   : {cfg.config_dir or '(not set)'}")
    print(f"  Backup dir   : {cfg.backup_dir or '(not set)'}")
    print(f"  Format       : {cfg.backup_format}")
    print(f"  Excludes     : {len(cfg.exclude_patterns)} rules")
    print(f"  Auto-backup  : {'ON' if cfg.auto_backup_no_change else 'OFF'}")

    if cfg.last_backup_time:
        try:
            dt = datetime.fromisoformat(cfg.last_backup_time)
            print(f"  Last backup  : {dt.strftime('%Y-%m-%d %H:%M:%S')}")
        except ValueError:
            print(f"  Last backup  : {cfg.last_backup_time}")
    else:
        print(f"  Last backup  : Never")

    if cfg.last_manifest:
        print(f"  Last files   : {len(cfg.last_manifest)}")
        total_size = sum(f.get("size", 0) for f in cfg.last_manifest.values())
        print(f"  Last size    : {format_size(total_size)}")

    # History
    history = cfg.backup_history
    if history:
        print(f"\n  Backup History (last {min(len(history), 20)} of {len(history)}):")
        print("-" * 60)
        for i, entry in enumerate(history[-20:], 1):
            ts = entry.get("timestamp", "?")
            path = entry.get("backup_path", "?")
            count = entry.get("file_count", 0)
            size = entry.get("total_size", 0)
            print(f"  {i}. {ts}")
            print(f"     Path : {path}")
            print(f"     Size : {format_size(size)} ({count} files)")
    else:
        print("\n  No backup history.")

    print(f"\n  Settings file: {SETTINGS_FILE}")
    print("=" * 60)


# ============================================================
# Interactive workflow
# ============================================================

def interactive_backup(cfg: BackupConfig) -> bool:
    """Run interactive backup workflow."""
    print("\n--- Smart Claude Backup ---\n")

    # 1. Config dir
    if not cfg.config_dir:
        found = discover_config_dirs()
        selected = prompt_select_config_dir(found, None)
        if not selected:
            print("No config directory selected. Aborting.")
            return False
        cfg.config_dir = str(selected)
        cfg.save()
        print(f"  Config dir: {selected}")
    else:
        found = discover_config_dirs()
        selected = prompt_select_config_dir(found, cfg.config_dir)
        if selected:
            cfg.config_dir = str(selected)
            cfg.save()
        print(f"  Config dir: {cfg.config_dir}")

    # 2. Backup dir
    if not cfg.backup_dir:
        default = str(Path.home() / "claude_backups")
        custom = input(f"\nBackup dir [{default}]: ").strip()
        backup_path = expand_path(custom) if custom else Path(default)
        backup_path.mkdir(parents=True, exist_ok=True)
        cfg.backup_dir = str(backup_path)
        cfg.save()
        print(f"  Backup dir: {backup_path}")
    else:
        print(f"  Backup dir: {cfg.backup_dir}")

    # 3. Backup format
    if cfg.backup_format not in VALID_FORMATS:
        cfg.backup_format = "zip"
    print(f"  Format: {cfg.backup_format}")

    # 4. Scan files
    print("\n  Scanning files...")
    source = Path(cfg.config_dir)
    files = scan_source(source, cfg.exclude_patterns)
    if not files:
        print("  No files found to backup.")
        return False
    print(f"  Found {len(files)} files.")

    # 5. Detect changes
    changes = detect_changes(files, cfg.last_manifest)
    current_hash = compute_tree_hash(files)
    last_hash = cfg.last_manifest and compute_tree_hash(cfg.last_manifest)

    # 6. Show manifest
    print_manifest(
        source,
        Path(cfg.backup_dir),
        cfg.backup_format,
        files,
        changes,
        current_hash,
        last_hash,
    )

    # 7. Confirm
    while True:
        confirmed = interactive_confirm(changes, cfg)
        if confirmed:
            break

        # Not confirmed - ask what to do
        print("\n  [e] Edit settings")
        print("  [l] List all files")
        print("  [n] Cancel")
        ans = input("  Choice: ").strip().lower()

        if ans == "e":
            cfg = edit_settings(cfg)
            # Re-scan after edit
            print("\n  Re-scanning...")
            source = Path(cfg.config_dir)
            files = scan_source(source, cfg.exclude_patterns)
            changes = detect_changes(files, cfg.last_manifest)
            current_hash = compute_tree_hash(files)
            print_manifest(
                source, Path(cfg.backup_dir), cfg.backup_format,
                files, changes, current_hash, last_hash,
            )
        elif ans == "l":
            print(f"\n  All files ({len(files)}):")
            for rel in sorted(files.keys()):
                print(f"    {rel} ({format_size(files[rel]['size'])})")
        elif ans == "n":
            print("  Cancelled.")
            return False

    # 8. Execute backup
    print("\n  Creating backup...")
    backup_path, manifest_path = create_backup(
        source, files, Path(cfg.backup_dir), cfg.backup_format,
    )
    print(f"  Backup created: {backup_path}")
    print(f"  Manifest: {manifest_path}")

    # 9. Update history
    cfg.last_manifest = files
    cfg.last_backup_time = datetime.now().isoformat()
    cfg.backup_history.append({
        "timestamp": cfg.last_backup_time,
        "backup_path": str(backup_path),
        "manifest_path": str(manifest_path),
        "file_count": len(files),
        "total_size": sum(f["size"] for f in files.values()),
        "tree_hash": current_hash,
        "has_changes": changes["has_changes"],
    })
    cfg.backup_history = cfg.backup_history[-20:]
    cfg.save()
    print("  Settings saved.")
    return True


def run_auto_backup(cfg: BackupConfig) -> bool:
    """Run non-interactive backup using saved settings."""
    if not cfg.config_dir:
        print("Config dir not set. Run with --interactive first.")
        return False
    if not cfg.backup_dir:
        print("Backup dir not set. Run with --interactive first.")
        return False

    source = Path(cfg.config_dir)
    backup_dir = Path(cfg.backup_dir)
    fmt = cfg.backup_format

    if not source.exists():
        print(f"Config dir not found: {source}")
        return False

    files = scan_source(source, cfg.exclude_patterns)
    if not files:
        print("No files to backup.")
        return False

    changes = detect_changes(files, cfg.last_manifest)
    current_hash = compute_tree_hash(files)

    if not changes["has_changes"] and cfg.auto_backup_no_change:
        print("No changes. Auto-backing up...")
    else:
        print(f"Changes: +{len(changes['added'])} -{len(changes['removed'])} ~{len(changes['modified'])}")

    backup_path, manifest_path = create_backup(source, files, backup_dir, fmt)
    print(f"Backup: {backup_path}")

    cfg.last_manifest = files
    cfg.last_backup_time = datetime.now().isoformat()
    cfg.backup_history.append({
        "timestamp": cfg.last_backup_time,
        "backup_path": str(backup_path),
        "manifest_path": str(manifest_path),
        "file_count": len(files),
        "total_size": sum(f["size"] for f in files.values()),
        "tree_hash": current_hash,
        "has_changes": changes["has_changes"],
    })
    cfg.backup_history = cfg.backup_history[-20:]
    cfg.save()
    return True


# ============================================================
# Main entry
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smart backup for Claude Code CLI config.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python backup.py --interactive          Interactive mode (recommended first time)
  python backup.py --backup               Auto backup with saved settings
  python backup.py --list                 List files without backing up
  python backup.py --status               Show settings and history
  python backup.py --config               Edit settings only
  python backup.py --reset                Reset all settings
  python backup.py --config-dir ~/.claude --backup-dir ~/backups --format zip --yes
        """,
    )
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
    parser.add_argument("--backup", "-b", action="store_true", help="Auto backup")
    parser.add_argument("--list", action="store_true", help="List files only")
    parser.add_argument("--status", "-s", action="store_true", help="Show status")
    parser.add_argument("--config", action="store_true", help="Edit settings")
    parser.add_argument("--reset", action="store_true", help="Reset all settings")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation")

    parser.add_argument("--config-dir", help="Override config directory")
    parser.add_argument("--backup-dir", help="Override backup directory")
    parser.add_argument("--format", choices=VALID_FORMATS, help="Override format")
    parser.add_argument("--exclude", action="append", help="Additional exclude rule (can repeat)")

    args = parser.parse_args()

    # Load config
    cfg = BackupConfig.load()

    # Reset
    if args.reset:
        if SETTINGS_FILE.exists():
            SETTINGS_FILE.unlink()
            print("Settings reset.")
        else:
            print("No settings to reset.")
        return 0

    # Show status
    if args.status:
        show_status(cfg)
        return 0

    # Edit config
    if args.config:
        edit_settings(cfg)
        return 0

    # Apply overrides
    if args.config_dir:
        p = expand_path(args.config_dir)
        if p.exists() and p.is_dir():
            cfg.config_dir = str(p)
        else:
            print(f"Config dir not found: {p}")
            return 1

    if args.backup_dir:
        p = expand_path(args.backup_dir)
        p.mkdir(parents=True, exist_ok=True)
        cfg.backup_dir = str(p)

    if args.format:
        cfg.backup_format = args.format

    if args.exclude:
        cfg.exclude_patterns.extend(args.exclude)

    # Save overrides
    if args.config_dir or args.backup_dir or args.format or args.exclude:
        cfg.save()

    # Interactive mode
    if args.interactive or (not args.backup and not args.list):
        success = interactive_backup(cfg)
        return 0 if success else 1

    # List mode
    if args.list:
        if not cfg.config_dir:
            print("Config dir not set. Run with --interactive first.")
            return 1
        source = Path(cfg.config_dir)
        files = scan_source(source, cfg.exclude_patterns)
        print(f"\nFiles to backup ({len(files)}):")
        for rel in sorted(files.keys()):
            print(f"  {rel} ({format_size(files[rel]['size'])})")
        total = sum(f["size"] for f in files.values())
        print(f"\nTotal: {len(files)} files, {format_size(total)}")
        return 0

    # Auto backup
    if args.backup:
        success = run_auto_backup(cfg)
        return 0 if success else 1

    # Default: show help + status
    parser.print_help()
    print()
    show_status(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
