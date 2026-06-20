#!/usr/bin/env python3
"""
Claude Code CLI 智能备份工具
- 自动查找 Claude Code 配置目录
- 智能排除临时文件和依赖文件
- 支持多种备份格式 (zip, tar.gz, dir)
- 变更检测与确认机制
- 设置自动记忆
"""

import os
import sys
import json
import hashlib
import shutil
import zipfile
import tarfile
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Set, Tuple, Optional

# ============================================================
# 常量定义
# ============================================================

# 默认排除模式 (gitignore 风格简化版)
DEFAULT_EXCLUDE_PATTERNS = [
    # 临时文件
    "*.tmp", "*.temp", "*.swp", "*.swo", "*~", ".DS_Store", "Thumbs.db",
    # 依赖目录
    "node_modules", "__pycache__", "*.pyc", ".venv", "venv", "env",
    # 缓存
    ".cache", "cache", "*.log", "logs/",
    # 构建产物
    "dist/", "build/", "*.egg-info/",
    # 大文件常见格式 (可选排除)
    # "*.zip", "*.tar.gz", "*.tar",
]

# Claude Code 配置目录常见位置
CLAUDE_CONFIG_CANDIDATES = [
    # macOS
    "~/Library/Application Support/Claude",
    "~/.claude",
    # Linux
    "~/.config/claude",
    "~/.claude",
    # Windows
    "%APPDATA%/Claude",
    "%USERPROFILE%/.claude",
    # 通用
    "./.claude",
]

# 设置文件名
SETTINGS_FILENAME = "backup_settings.json"
BACKUP_MANIFEST_FILENAME = "backup_manifest.json"


# ============================================================
# 工具函数
# ============================================================

def expand_path(path_str: str) -> Path:
    """展开用户目录和环境变量"""
    expanded = os.path.expanduser(path_str)
    expanded = os.path.expandvars(expanded)
    return Path(expanded).resolve()


def file_md5(filepath: Path) -> str:
    """计算文件 MD5 哈希"""
    h = hashlib.md5()
    try:
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except (IOError, OSError):
        return ""


def match_pattern(name: str, pattern: str) -> bool:
    """简单 glob 模式匹配 (支持 * 和 ?)"""
    import fnmatch
    return fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(name.lower(), pattern.lower())


def should_exclude(rel_path: str, name: str, patterns: List[str]) -> bool:
    """检查路径是否应该被排除"""
    for pat in patterns:
        pat = pat.strip()
        if not pat or pat.startswith("#"):
            continue
        # 目录模式 (以 / 结尾)
        if pat.endswith("/"):
            dir_name = pat.rstrip("/")
            if name == dir_name or match_pattern(name, dir_name):
                return True
        # 普通模式
        if match_pattern(name, pat):
            return True
        # 检查路径部分
        parts = rel_path.replace("\\", "/").split("/")
        for part in parts:
            if match_pattern(part, pat):
                return True
    return False


# ============================================================
# 设置管理
# ============================================================

class BackupSettings:
    """备份设置管理 - 自动记忆用户配置"""

    def __init__(self, settings_path: Path):
        self.settings_path = settings_path
        self.data: Dict = {
            "claude_config_dir": "",
            "backup_dir": "",
            "backup_format": "zip",  # zip, tar.gz, dir
            "exclude_patterns": DEFAULT_EXCLUDE_PATTERNS.copy(),
            "last_backup_time": "",
            "last_backup_hash": "",
            "auto_backup_unchanged": True,
            "backup_history": [],
        }
        self.load()

    def load(self):
        """从文件加载设置"""
        if self.settings_path.exists():
            try:
                with open(self.settings_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self.data.update(saved)
            except (json.JSONDecodeError, IOError):
                pass  # 文件损坏时使用默认值

    def save(self):
        """保存设置到文件"""
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.settings_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value):
        self.data[key] = value
        self.save()


# ============================================================
# 配置目录查找
# ============================================================

def find_claude_config_dir() -> Optional[Path]:
    """自动查找 Claude Code 配置目录"""
    for candidate in CLAUDE_CONFIG_CANDIDATES:
        path = expand_path(candidate)
        if path.exists() and path.is_dir():
            # 检查是否有 Claude 相关文件
            has_claude_files = any(
                path.glob("*.json") or path.glob("*.db") or
                path.glob("settings*") or path.glob("config*")
            )
            if has_claude_files or path.name.lower() in ["claude", ".claude"]:
                return path
    # 尝试环境变量
    env_vars = ["CLAUDE_CONFIG_DIR", "CLAUDE_HOME"]
    for env in env_vars:
        if env in os.environ:
            path = expand_path(os.environ[env])
            if path.exists() and path.is_dir():
                return path
    return None


def scan_config_dir(config_dir: Path, exclude_patterns: List[str]) -> List[Tuple[str, int, str]]:
    """扫描配置目录，返回文件列表 [(相对路径, 大小, md5)]"""
    files = []
    config_dir = config_dir.resolve()
    for root, dirs, filenames in os.walk(config_dir):
        root_path = Path(root)
        rel_root = root_path.relative_to(config_dir)
        rel_root_str = str(rel_root) if str(rel_root) != "." else ""

        # 过滤目录
        dirs_to_remove = []
        for d in dirs:
            rel_d = f"{rel_root_str}/{d}" if rel_root_str else d
            if should_exclude(rel_d, d, exclude_patterns):
                dirs_to_remove.append(d)
        for d in dirs_to_remove:
            dirs.remove(d)

        # 收集文件
        for fname in filenames:
            rel_path = f"{rel_root_str}/{fname}" if rel_root_str else fname
            if should_exclude(rel_path, fname, exclude_patterns):
                continue
            full_path = root_path / fname
            try:
                size = full_path.stat().st_size
                md5 = file_md5(full_path)
                files.append((rel_path, size, md5))
            except (IOError, OSError):
                continue
    return files


# ============================================================
# 变更检测
# ============================================================

def compute_tree_hash(files: List[Tuple[str, int, str]]) -> str:
    """计算整个目录树的哈希"""
    h = hashlib.md5()
    for rel_path, size, md5 in sorted(files):
        h.update(f"{rel_path}:{size}:{md5}".encode("utf-8"))
    return h.hexdigest()


def detect_changes(
    current_files: List[Tuple[str, int, str]],
    last_manifest_path: Optional[Path]
) -> Tuple[List[str], List[str], List[str]]:
    """
    检测与上次备份的差异
    返回: (新增文件列表, 删除文件列表, 修改文件列表)
    """
    current_map = {rel: (size, md5) for rel, size, md5 in current_files}
    last_map: Dict[str, Tuple[int, str]] = {}

    if last_manifest_path and last_manifest_path.exists():
        try:
            with open(last_manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
                for item in manifest.get("files", []):
                    last_map[item["path"]] = (item["size"], item["md5"])
        except (json.JSONDecodeError, IOError, KeyError):
            pass

    current_keys = set(current_map.keys())
    last_keys = set(last_map.keys())

    added = sorted(current_keys - last_keys)
    removed = sorted(last_keys - current_keys)
    modified = []
    for key in sorted(current_keys & last_keys):
        if current_map[key][1] != last_map[key][1]:
            modified.append(key)

    return added, removed, modified


# ============================================================
# 备份执行
# ============================================================

def create_backup(
    config_dir: Path,
    files: List[Tuple[str, int, str]],
    backup_dir: Path,
    backup_format: str,
) -> Tuple[Path, Path]:
    """
    创建备份
    返回: (备份文件路径, manifest路径)
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"claude_backup_{timestamp}"

    # 写入 manifest
    manifest = {
        "version": "1.0",
        "created_at": datetime.now().isoformat(),
        "source_dir": str(config_dir),
        "file_count": len(files),
        "total_size": sum(size for _, size, _ in files),
        "tree_hash": compute_tree_hash(files),
        "files": [
            {"path": rel, "size": size, "md5": md5}
            for rel, size, md5 in sorted(files)
        ],
    }

    if backup_format == "dir":
        # 目录复制模式
        backup_path = backup_dir / base_name
        backup_path.mkdir(parents=True, exist_ok=True)

        for rel_path, _, _ in files:
            src = config_dir / rel_path
            dst = backup_path / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        manifest_path = backup_path / BACKUP_MANIFEST_FILENAME
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

    elif backup_format == "tar.gz":
        backup_path = backup_dir / f"{base_name}.tar.gz"
        with tarfile.open(backup_path, "w:gz") as tar:
            for rel_path, _, _ in files:
                src = config_dir / rel_path
                tar.add(src, arcname=rel_path)
            # 添加 manifest
            manifest_path = backup_dir / f"{base_name}_manifest.json"
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
            tar.add(manifest_path, arcname=BACKUP_MANIFEST_FILENAME)

    else:  # zip (默认)
        backup_path = backup_dir / f"{base_name}.zip"
        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel_path, _, _ in files:
                src = config_dir / rel_path
                zf.write(src, arcname=rel_path)
            # 添加 manifest
            manifest_json = json.dumps(manifest, indent=2, ensure_ascii=False)
            zf.writestr(BACKUP_MANIFEST_FILENAME, manifest_json)

        manifest_path = backup_dir / f"{base_name}_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

    return backup_path, manifest_path


# ============================================================
# 交互界面
# ============================================================

def print_banner():
    print("=" * 60)
    print("  Claude Code 智能备份工具")
    print("=" * 60)
    print()


def print_file_list(files: List[Tuple[str, int, str]], title: str = "文件清单"):
    """打印文件列表"""
    print(f"\n{title} ({len(files)} 个文件):")
    print("-" * 60)
    total_size = 0
    for rel_path, size, _ in files:
        total_size += size
        size_str = format_size(size)
        print(f"  {rel_path}  [{size_str}]")
    print("-" * 60)
    print(f"  总计: {len(files)} 个文件, {format_size(total_size)}")
    print()


def format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def print_changes(added: List[str], removed: List[str], modified: List[str]):
    """打印变更信息"""
    if not added and not removed and not modified:
        print("  ✅ 与上次备份相比，没有变化")
        return True  # 无变化

    print("\n📋 变更检测结果:")
    print("-" * 60)

    if added:
        print(f"  🆕 新增文件 ({len(added)}):")
        for f in added:
            print(f"     + {f}")

    if removed:
        print(f"  🗑️  删除文件 ({len(removed)}):")
        for f in removed:
            print(f"     - {f}")

    if modified:
        print(f"  ✏️  修改文件 ({len(modified)}):")
        for f in modified:
            print(f"     ~ {f}")

    print("-" * 60)
    total_changes = len(added) + len(removed) + len(modified)
    print(f"  共 {total_changes} 处变更")
    print()
    return False  # 有变化


def interactive_confirm(settings: BackupSettings, files: List[Tuple[str, int, str]],
                        no_changes: bool) -> bool:
    """交互式确认备份"""
    if no_changes and settings.get("auto_backup_unchanged", True):
        print("  💡 设置了无变化自动备份，将自动执行...")
        return True

    print("当前备份设置:")
    print(f"  配置目录: {settings.get('claude_config_dir')}")
    print(f"  备份目录: {settings.get('backup_dir')}")
    print(f"  备份格式: {settings.get('backup_format')}")
    print(f"  排除规则: {len(settings.get('exclude_patterns', []))} 条")
    print()

    while True:
        if no_changes:
            prompt = "确认执行备份? [Y/n] "
        else:
            prompt = "确认执行备份? [Y/n] (输入 e 修改设置, l 查看完整清单) "

        try:
            choice = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消")
            return False

        if choice in ("y", "yes", ""):
            return True
        elif choice in ("n", "no", "q", "quit"):
            return False
        elif choice == "e":
            modify_settings_interactive(settings)
        elif choice == "l":
            print_file_list(files, "完整文件清单")
        else:
            print("  无效输入，请输入 y/n/e/l")


def modify_settings_interactive(settings: BackupSettings):
    """交互式修改设置"""
    print("\n⚙️  修改设置")
    print("-" * 60)
    print("  1. 修改配置目录路径")
    print("  2. 修改备份目录路径")
    print("  3. 修改备份格式 (zip/tar.gz/dir)")
    print("  4. 管理排除规则")
    print("  5. 切换无变化自动备份")
    print("  0. 返回")
    print("-" * 60)

    try:
        choice = input("请选择 [0-5]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if choice == "1":
        new_path = input(f"  配置目录路径 (当前: {settings.get('claude_config_dir')}): ").strip()
        if new_path:
            p = expand_path(new_path)
            if p.exists() and p.is_dir():
                settings.set("claude_config_dir", str(p))
                print(f"  ✅ 已更新: {p}")
            else:
                print(f"  ❌ 目录不存在: {p}")

    elif choice == "2":
        new_path = input(f"  备份目录路径 (当前: {settings.get('backup_dir')}): ").strip()
        if new_path:
            p = expand_path(new_path)
            p.mkdir(parents=True, exist_ok=True)
            settings.set("backup_dir", str(p))
            print(f"  ✅ 已更新: {p}")

    elif choice == "3":
        fmt = input(f"  备份格式 zip/tar.gz/dir (当前: {settings.get('backup_format')}): ").strip().lower()
        if fmt in ("zip", "tar.gz", "dir"):
            settings.set("backup_format", fmt)
            print(f"  ✅ 已更新为: {fmt}")
        else:
            print("  ❌ 无效格式，支持: zip, tar.gz, dir")

    elif choice == "4":
        manage_exclude_patterns(settings)

    elif choice == "5":
        current = settings.get("auto_backup_unchanged", True)
        settings.set("auto_backup_unchanged", not current)
        print(f"  ✅ 无变化自动备份: {'开启' if not current else '关闭'}")

    print()


def manage_exclude_patterns(settings: BackupSettings):
    """管理排除规则"""
    patterns = settings.get("exclude_patterns", [])
    print(f"\n  当前排除规则 ({len(patterns)} 条):")
    for i, p in enumerate(patterns, 1):
        print(f"    {i}. {p}")
    print()
    print("  操作: [a]添加  [d]删除编号  [r]重置默认  [b]返回")

    try:
        action = input("  选择操作: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if action == "a":
        new_pat = input("  输入新规则: ").strip()
        if new_pat and new_pat not in patterns:
            patterns.append(new_pat)
            settings.set("exclude_patterns", patterns)
            print(f"  ✅ 已添加: {new_pat}")
    elif action == "d":
        idx_str = input("  要删除的编号: ").strip()
        try:
            idx = int(idx_str) - 1
            if 0 <= idx < len(patterns):
                removed = patterns.pop(idx)
                settings.set("exclude_patterns", patterns)
                print(f"  ✅ 已删除: {removed}")
        except ValueError:
            print("  ❌ 无效编号")
    elif action == "r":
        settings.set("exclude_patterns", DEFAULT_EXCLUDE_PATTERNS.copy())
        print(f"  ✅ 已重置为默认 {len(DEFAULT_EXCLUDE_PATTERNS)} 条规则")


# ============================================================
# 主流程
# ============================================================

def get_settings_path() -> Path:
    """获取设置文件路径（脚本同级目录）"""
    script_dir = Path(__file__).resolve().parent
    return script_dir / SETTINGS_FILENAME


def init_settings(settings: BackupSettings) -> bool:
    """初始化设置 - 首次运行时引导配置"""
    needs_save = False

    # 配置目录
    if not settings.get("claude_config_dir"):
        print("🔍 正在自动查找 Claude Code 配置目录...")
        found = find_claude_config_dir()
        if found:
            print(f"  ✅ 找到配置目录: {found}")
            try:
                confirm = input("  使用此目录? [Y/n] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n已取消")
                return False
            if confirm in ("y", "yes", ""):
                settings.set("claude_config_dir", str(found))
                needs_save = True
            else:
                custom = input("  请输入自定义路径: ").strip()
                if custom:
                    p = expand_path(custom)
                    if p.exists() and p.is_dir():
                        settings.set("claude_config_dir", str(p))
                        needs_save = True
                    else:
                        print(f"  ❌ 目录不存在: {p}")
                        return False
        else:
            print("  ⚠️  未自动找到 Claude Code 配置目录")
            custom = input("  请输入配置目录路径: ").strip()
            if custom:
                p = expand_path(custom)
                if p.exists() and p.is_dir():
                    settings.set("claude_config_dir", str(p))
                    needs_save = True
                else:
                    print(f"  ❌ 目录不存在: {p}")
                    return False
            else:
                return False

    # 备份目录
    if not settings.get("backup_dir"):
        default_backup = str(Path.home() / "claude_backups")
        try:
            custom = input(f"  备份目录 (默认: {default_backup}): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消")
            return False
        backup_path = expand_path(custom) if custom else Path(default_backup)
        backup_path.mkdir(parents=True, exist_ok=True)
        settings.set("backup_dir", str(backup_path))
        needs_save = True

    if needs_save:
        settings.save()

    return bool(settings.get("claude_config_dir"))


def main():
    parser = argparse.ArgumentParser(
        description="Claude Code 智能备份工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python claude_backup.py              # 交互式备份
  python claude_backup.py --auto       # 全自动模式 (无交互)
  python claude_backup.py --list       # 只列出文件不备份
  python claude_backup.py --config     # 只修改设置
  python claude_backup.py --format zip # 指定备份格式
        """
    )
    parser.add_argument("--auto", action="store_true", help="全自动模式，无交互")
    parser.add_argument("--list", action="store_true", help="只列出文件清单，不备份")
    parser.add_argument("--config", action="store_true", help="只打开设置菜单")
    parser.add_argument("--format", choices=["zip", "tar.gz", "dir"], help="指定备份格式")
    parser.add_argument("--config-dir", help="指定 Claude 配置目录")
    parser.add_argument("--backup-dir", help="指定备份输出目录")
    parser.add_argument("--settings", help="指定设置文件路径")

    args = parser.parse_args()

    # 初始化设置
    settings_path = expand_path(args.settings) if args.settings else get_settings_path()
    settings = BackupSettings(settings_path)

    if not args.auto:
        print_banner()

    # 命令行参数覆盖
    if args.config_dir:
        p = expand_path(args.config_dir)
        if p.exists() and p.is_dir():
            settings.set("claude_config_dir", str(p))

    if args.backup_dir:
        p = expand_path(args.backup_dir)
        p.mkdir(parents=True, exist_ok=True)
        settings.set("backup_dir", str(p))

    if args.format:
        settings.set("backup_format", args.format)

    # 仅配置模式
    if args.config:
        while True:
            modify_settings_interactive(settings)
            try:
                again = input("继续修改设置? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if again not in ("y", "yes"):
                break
        print("设置已保存。")
        return 0

    # 初始化配置
    if not init_settings(settings):
        print("❌ 配置初始化失败")
        return 1

    config_dir = Path(settings.get("claude_config_dir"))
    backup_dir = Path(settings.get("backup_dir"))
    exclude_patterns = settings.get("exclude_patterns", [])
    backup_format = settings.get("backup_format", "zip")

    # 扫描文件
    if not args.auto:
        print(f"📂 扫描配置目录: {config_dir}")
    files = scan_config_dir(config_dir, exclude_patterns)

    if not files:
        print("⚠️  没有找到可备份的文件")
        return 1

    # 仅列表模式
    if args.list:
        print_file_list(files, "待备份文件清单")
        return 0

    # 查找上次备份的 manifest
    last_manifest = None
    history = settings.get("backup_history", [])
    if history:
        last_manifest_str = history[-1].get("manifest_path", "")
        if last_manifest_str:
            last_manifest = Path(last_manifest_str)
            if not last_manifest.exists():
                # 尝试在备份目录找最新的 manifest
                manifests = sorted(backup_dir.glob("*_manifest.json"))
                if manifests:
                    last_manifest = manifests[-1]
                else:
                    last_manifest = None

    # 变更检测
    added, removed, modified = detect_changes(files, last_manifest)
    no_changes = not added and not removed and not modified

    if not args.auto:
        print_changes(added, removed, modified)
        if not no_changes:
            # 显示前10个新增/修改的文件预览
            preview = added[:5] + modified[:5]
            if preview:
                print("  (输入 l 查看完整清单)")

    # 确认并执行
    if args.auto:
        do_backup = True
    else:
        do_backup = interactive_confirm(settings, files, no_changes)

    if not do_backup:
        print("已取消备份。")
        return 0

    # 执行备份
    if not args.auto:
        print("\n🚀 正在创建备份...")

    try:
        backup_path, manifest_path = create_backup(
            config_dir, files, backup_dir, backup_format
        )
    except Exception as e:
        print(f"❌ 备份失败: {e}")
        return 1

    # 更新历史
    tree_hash = compute_tree_hash(files)
    history.append({
        "timestamp": datetime.now().isoformat(),
        "backup_path": str(backup_path),
        "manifest_path": str(manifest_path),
        "file_count": len(files),
        "total_size": sum(size for _, size, _ in files),
        "tree_hash": tree_hash,
        "has_changes": not no_changes,
    })
    # 只保留最近 20 条历史
    history = history[-20:]
    settings.set("backup_history", history)
    settings.set("last_backup_time", datetime.now().isoformat())
    settings.set("last_backup_hash", tree_hash)
    settings.save()

    # 输出结果
    if args.auto:
        print(f"Backup created: {backup_path}")
    else:
        print()
        print("=" * 60)
        print("  ✅ 备份完成!")
        print("=" * 60)
        print(f"  备份文件: {backup_path}")
        print(f"  文件数量: {len(files)}")
        print(f"  总大小:   {format_size(sum(size for _, size, _ in files))}")
        print(f"  格式:     {backup_format}")
        print(f"  清单:     {manifest_path}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
