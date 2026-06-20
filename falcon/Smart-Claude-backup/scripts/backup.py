#!/usr/bin/env python3
"""Smart Claude Code CLI backup.

Locates the Claude Code config folder, remembers the choice, prints a manifest
for user confirmation, then writes a timestamped archive. Re-running with no
changes auto-backs up; changes can be edited interactively and are persisted.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import time
import zipfile
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Iterable, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CONFIG_PATH = SCRIPT_DIR / "backup_config.json"
DEFAULT_DEST = SKILL_DIR / "backups"

DEFAULT_EXCLUDES = [
    "node_modules", "__pycache__", ".venv", "venv",
    "*.log", "*.tmp", "*.lock", "*.pyc",
    ".DS_Store", "Thumbs.db",
    "cache", "tmp", "logs",
    ".cache", ".tmp",
]

VALID_FORMATS = ("zip", "tar.gz", "copy")


# ---------- config ----------

@dataclass
class BackupConfig:
    source: Optional[str] = None
    destination: str = str(DEFAULT_DEST)
    fmt: str = "zip"
    excludes: List[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDES))
    last_hash: Optional[str] = None
    last_backup: Optional[str] = None

    @classmethod
    def load(cls) -> "BackupConfig":
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                return cls(**{k: data.get(k, getattr(cls(), k)) for k in cls.__dataclass_fields__})
            except Exception as e:
                print(f"[warn] failed reading {CONFIG_PATH}: {e}; using defaults")
        return cls()

    def save(self) -> None:
        CONFIG_PATH.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


# ---------- discovery ----------

def candidate_sources() -> List[Path]:
    cands: List[Path] = []
    env = os.environ.get("CLAUDE_HOME")
    if env:
        cands.append(Path(env).expanduser())
    home = Path.home()
    cands += [
        home / ".claude",
        home / ".config" / "claude",
        home / ".config" / "claude-code",
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        cands.append(Path(appdata) / "Claude")
        cands.append(Path(appdata) / "claude-code")
    cands.append(Path.cwd() / ".claude")
    # de-dupe while preserving order
    seen, out = set(), []
    for p in cands:
        rp = str(p)
        if rp in seen:
            continue
        seen.add(rp)
        if p.exists():
            out.append(p)
    return out


def confirm_source(stored: Optional[str]) -> Path:
    if stored and Path(stored).expanduser().exists():
        cur = Path(stored).expanduser()
        ans = input(f"Use remembered Claude Code config folder?\n  {cur}\n[Y/n/path] ").strip()
        if ans == "" or ans.lower().startswith("y"):
            return cur
        if ans.lower() not in ("n", "no"):
            chosen = Path(ans).expanduser()
            if not chosen.exists():
                raise SystemExit(f"path does not exist: {chosen}")
            return chosen
    cands = candidate_sources()
    if not cands:
        manual = input("No Claude Code folder auto-detected. Enter path: ").strip()
        p = Path(manual).expanduser()
        if not p.exists():
            raise SystemExit(f"path does not exist: {p}")
        return p
    print("Detected candidate Claude Code folders:")
    for i, p in enumerate(cands, 1):
        print(f"  [{i}] {p}")
    print("  [m] enter a custom path")
    ans = input(f"Pick [1-{len(cands)}/m]: ").strip().lower()
    if ans == "m":
        p = Path(input("Custom path: ").strip()).expanduser()
        if not p.exists():
            raise SystemExit(f"path does not exist: {p}")
        return p
    try:
        return cands[int(ans) - 1]
    except (ValueError, IndexError):
        raise SystemExit("invalid selection")


# ---------- file walking & hashing ----------

def is_excluded(rel: Path, excludes: Iterable[str]) -> bool:
    parts = rel.parts
    name = rel.name
    for pat in excludes:
        if "/" in pat or "\\" in pat:
            if fnmatch.fnmatch(str(rel).replace("\\", "/"), pat):
                return True
        else:
            if any(fnmatch.fnmatch(p, pat) for p in parts):
                return True
            if fnmatch.fnmatch(name, pat):
                return True
    return False


def iter_files(source: Path, excludes: List[str]) -> Iterable[Path]:
    for root, dirs, files in os.walk(source):
        root_p = Path(root)
        rel_root = root_p.relative_to(source) if root_p != source else Path()
        # prune dirs in-place
        dirs[:] = [d for d in dirs if not is_excluded(rel_root / d, excludes)]
        for f in files:
            rel = rel_root / f
            if is_excluded(rel, excludes):
                continue
            yield root_p / f


def tree_hash(source: Path, excludes: List[str]) -> str:
    h = hashlib.sha256()
    files = sorted(iter_files(source, excludes), key=lambda p: str(p.relative_to(source)))
    for fp in files:
        rel = fp.relative_to(source).as_posix().encode("utf-8")
        h.update(rel + b"\0")
        try:
            with fp.open("rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    h.update(chunk)
        except OSError as e:
            h.update(f"<unreadable:{e}>".encode())
        h.update(b"\n")
    return h.hexdigest()


# ---------- manifest ----------

def print_manifest(cfg: BackupConfig, source: Path, file_count: int, total_bytes: int, current_hash: str) -> None:
    print("\n=== Smart Claude Code Backup Manifest ===")
    print(f"  Source       : {source}")
    print(f"  Destination  : {cfg.destination}")
    print(f"  Format       : {cfg.fmt}")
    print(f"  Excludes     : {', '.join(cfg.excludes)}")
    print(f"  Files counted: {file_count}")
    print(f"  Total bytes  : {total_bytes:,}")
    print(f"  Current hash : {current_hash[:16]}...")
    print(f"  Last hash    : {(cfg.last_hash or '(none)')[:16]}...")
    print(f"  Last backup  : {cfg.last_backup or '(never)'}")
    changed = current_hash != cfg.last_hash
    print(f"  Status       : {'CHANGED since last backup' if changed else 'UNCHANGED since last backup'}")
    print("=========================================")


def edit_settings(cfg: BackupConfig, source: Path) -> tuple[BackupConfig, Path]:
    print("\nEdit settings (blank keeps current):")
    s = input(f"  source [{source}]: ").strip()
    if s:
        sp = Path(s).expanduser()
        if not sp.exists():
            print(f"  [warn] {sp} not found; keeping previous.")
        else:
            source = sp
            cfg.source = str(sp)
    d = input(f"  destination [{cfg.destination}]: ").strip()
    if d:
        cfg.destination = str(Path(d).expanduser())
    f = input(f"  format {VALID_FORMATS} [{cfg.fmt}]: ").strip()
    if f:
        if f not in VALID_FORMATS:
            print(f"  [warn] invalid format; keeping {cfg.fmt}")
        else:
            cfg.fmt = f
    e = input(f"  excludes (comma-sep, blank=keep, '+x,y' append, '-x' remove): ").strip()
    if e:
        if e.startswith("+"):
            for tok in e[1:].split(","):
                tok = tok.strip()
                if tok and tok not in cfg.excludes:
                    cfg.excludes.append(tok)
        elif e.startswith("-"):
            for tok in e[1:].split(","):
                tok = tok.strip()
                if tok in cfg.excludes:
                    cfg.excludes.remove(tok)
        else:
            cfg.excludes = [t.strip() for t in e.split(",") if t.strip()]
    return cfg, source


# ---------- archive ----------

def make_archive(source: Path, files: List[Path], dest_dir: Path, fmt: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = f"claude-config-{stamp}"
    if fmt == "zip":
        out = dest_dir / f"{base}.zip"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for fp in files:
                zf.write(fp, arcname=str(fp.relative_to(source)))
        return out
    if fmt == "tar.gz":
        out = dest_dir / f"{base}.tar.gz"
        with tarfile.open(out, "w:gz") as tf:
            for fp in files:
                tf.add(fp, arcname=str(fp.relative_to(source)))
        return out
    if fmt == "copy":
        out = dest_dir / base
        out.mkdir(parents=True, exist_ok=True)
        for fp in files:
            target = out / fp.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fp, target)
        return out
    raise ValueError(f"unsupported format: {fmt}")


# ---------- main ----------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Smart backup for Claude Code CLI config.")
    ap.add_argument("--source")
    ap.add_argument("--dest")
    ap.add_argument("--format", choices=VALID_FORMATS)
    ap.add_argument("--yes", action="store_true", help="skip manifest confirmation")
    ap.add_argument("--force-prompt", action="store_true", help="prompt even when unchanged")
    ap.add_argument("--reset", action="store_true", help="wipe stored config and exit")
    ap.add_argument("--config-dir", help="(unused placeholder for future)")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    if args.reset:
        if CONFIG_PATH.exists():
            CONFIG_PATH.unlink()
            print(f"removed {CONFIG_PATH}")
        else:
            print("no stored config to reset")
        return 0

    cfg = BackupConfig.load()
    if args.dest:
        cfg.destination = str(Path(args.dest).expanduser())
    if args.format:
        cfg.fmt = args.format

    if args.source:
        source = Path(args.source).expanduser()
        if not source.exists():
            print(f"[error] --source {source} not found", file=sys.stderr)
            return 2
    else:
        source = confirm_source(cfg.source)
    cfg.source = str(source)

    files = list(iter_files(source, cfg.excludes))
    total_bytes = sum(fp.stat().st_size for fp in files if fp.is_file())
    current_hash = tree_hash(source, cfg.excludes)
    unchanged = current_hash == cfg.last_hash

    print_manifest(cfg, source, len(files), total_bytes, current_hash)

    auto = unchanged and not args.force_prompt
    if args.yes or auto:
        if auto:
            print("\n[info] no changes detected -> auto-confirming backup.")
        proceed = True
    else:
        while True:
            ans = input("Proceed? [y]es / [e]dit / [n]o: ").strip().lower()
            if ans in ("y", "yes"):
                proceed = True
                break
            if ans in ("n", "no", ""):
                proceed = False
                break
            if ans in ("e", "edit"):
                cfg, source = edit_settings(cfg, source)
                files = list(iter_files(source, cfg.excludes))
                total_bytes = sum(fp.stat().st_size for fp in files if fp.is_file())
                current_hash = tree_hash(source, cfg.excludes)
                print_manifest(cfg, source, len(files), total_bytes, current_hash)
                continue
            print("  please answer y / e / n")

    if not proceed:
        cfg.save()
        print("aborted; settings saved.")
        return 1

    dest_dir = Path(cfg.destination).expanduser()
    out = make_archive(source, files, dest_dir, cfg.fmt)
    cfg.last_hash = current_hash
    cfg.last_backup = time.strftime("%Y-%m-%d %H:%M:%S")
    cfg.save()
    print(f"\n[ok] backup written: {out}")
    print(f"[ok] settings stored: {CONFIG_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
