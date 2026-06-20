#!/usr/bin/env python3
"""
Smart Claude Backup - Claude Code 配置智能备份工具

功能：
- 自动查找 Claude Code 配置目录
- 智能排除临时文件和依赖文件
- 支持多种备份格式（zip / tar.gz / 目录拷贝）
- 清单式变更确认机制
- 自动记忆用户设置
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import zipfile
from datetime import datetime
from pathlib import Path
from fnmatch import fnmatch


# ============================================================
# 常量定义
# ============================================================

SETTINGS_DIR = Path.home() / ".smart-claude-backup"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"
BACKUP_HASH_FILE = "backup_manifest.json"

# 常见 Claude Code 配置目录候选
CONFIG_CANDIDATES = [
    "~/.claude",
    "~/.config/claude",
    "~/Library/Application Support/Claude",
    "~/AppData/Roaming/Claude",
    "~/AppData/Local/Claude",
]

# 默认排除规则
DEFAULT_EXCLUDES = [
    # 临时文件
    "*.tmp", "*.temp", "*~", "*.swp", "*.swo",
    ".DS_Store", "Thumbs.db", "desktop.ini",
    # 缓存
    "*.cache", "cache/", "__pycache__/", ".cache/",
    "node_modules/",
    # 日志
    "*.log", "logs/", "*.log.*",
    # 锁文件
    "*.lock", ".lock",
    # 二进制/大文件
    "*.bin", "*.exe", "*.dll", "*.so", "*.dylib",
    # 其他
    ".git/",
]


# ============================================================
# 设置管理
# ============================================================

def load_settings():
    """加载保存的设置"""
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return get_default_settings()


def get_default_settings():
    """获取默认设置"""
    return {
        "config_dir": None,           # Claude Code 配置目录
        "backup_dir": None,           # 备份目标目录
        "backup_format": "zip",       # 备份格式: zip, targz, copy
        "exclude_patterns": DEFAULT_EXCLUDES.copy(),
        "auto_backup_no_change": True,  # 无变化时自动备份
        "last_backup_time": None,
        "last_backup_manifest": None,   # 上次备份的文件哈希清单
    }


def save_settings(settings):
    """保存设置"""
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


def reset_settings():
    """重置所有设置"""
    if SETTINGS_FILE.exists():
        SETTINGS_FILE.unlink()
    print("✓ 所有设置已重置")


# ============================================================
# 配置目录发现
# ============================================================

def discover_config_dirs():
    """扫描所有可能的 Claude Code 配置目录"""
    found = []
    for candidate in CONFIG_CANDIDATES:
        path = Path(os.path.expanduser(candidate))
        if path.exists() and path.is_dir():
            # 检查是否有 claude 相关的配置文件
            has_config = any(
                f.name.startswith("claude") or f.name.endswith(".json") or f.name.endswith(".yaml") or f.name.endswith(".yml")
                for f in path.iterdir()
                if f.is_file()
            )
            # 或者目录名本身就很明确
            if has_config or "claude" in path.name.lower():
                found.append(str(path))
    return found


def confirm_config_dir(settings):
    """确认配置目录（交互式）"""
    if settings.get("config_dir"):
        path = Path(settings["config_dir"])
        if path.exists():
            print(f"已保存的配置目录: {path}")
            resp = input("是否继续使用此目录? [Y/n] ").strip().lower()
            if resp in ("", "y", "yes"):
                return settings["config_dir"]

    # 自动发现
    print("\n正在扫描 Claude Code 配置目录...")
    candidates = discover_config_dirs()

    if candidates:
        print(f"\n发现 {len(candidates)} 个候选目录:")
        for i, path in enumerate(candidates, 1):
            print(f"  [{i}] {path}")
        print(f"  [0] 手动指定路径")

        while True:
            choice = input("\n请选择配置目录 [0-" + str(len(candidates)) + "]: ").strip()
            if choice == "0":
                manual = input("请输入配置目录路径: ").strip()
                manual_path = Path(os.path.expanduser(manual))
                if manual_path.exists() and manual_path.is_dir():
                    settings["config_dir"] = str(manual_path)
                    save_settings(settings)
                    print(f"✓ 已保存配置目录: {manual_path}")
                    return str(manual_path)
                else:
                    print("✗ 目录不存在，请重试")
            elif choice.isdigit() and 1 <= int(choice) <= len(candidates):
                selected = candidates[int(choice) - 1]
                settings["config_dir"] = selected
                save_settings(settings)
                print(f"✓ 已保存配置目录: {selected}")
                return selected
            else:
                print("无效选择，请重试")
    else:
        print("未自动发现配置目录，请手动指定")
        while True:
            manual = input("请输入配置目录路径: ").strip()
            manual_path = Path(os.path.expanduser(manual))
            if manual_path.exists() and manual_path.is_dir():
                settings["config_dir"] = str(manual_path)
                save_settings(settings)
                print(f"✓ 已保存配置目录: {manual_path}")
                return str(manual_path)
            else:
                print("✗ 目录不存在，请重试")


# ============================================================
# 备份目标设置
# ============================================================

def confirm_backup_dir(settings):
    """确认备份目标目录"""
    default_backup = str(Path.home() / "claude-backups")

    if settings.get("backup_dir"):
        path = Path(settings["backup_dir"])
        print(f"已保存的备份目录: {path}")
        resp = input("是否继续使用此目录? [Y/n] ").strip().lower()
        if resp in ("", "y", "yes"):
            path.mkdir(parents=True, exist_ok=True)
            return str(path)

    resp = input(f"\n备份目标目录 [{default_backup}]: ").strip()
    backup_dir = resp if resp else default_backup
    backup_path = Path(os.path.expanduser(backup_dir))
    backup_path.mkdir(parents=True, exist_ok=True)

    settings["backup_dir"] = str(backup_path)
    save_settings(settings)
    print(f"✓ 已保存备份目录: {backup_path}")
    return str(backup_path)


def confirm_backup_format(settings):
    """确认备份格式"""
    formats = {
        "1": ("zip", "ZIP 压缩包 - 跨平台兼容，压缩率适中"),
        "2": ("targz", "tar.gz 压缩包 - Unix 风格，压缩率较高"),
        "3": ("copy", "目录拷贝 - 直接复制文件，便于直接查看"),
    }

    if settings.get("backup_format"):
        fmt = settings["backup_format"]
        fmt_name = dict((v[0], v[1]) for v in formats.values()).get(fmt, fmt)
        print(f"已保存的备份格式: {fmt} ({fmt_name})")
        resp = input("是否继续使用此格式? [Y/n] ").strip().lower()
        if resp in ("", "y", "yes"):
            return fmt

    print("\n可用备份格式:")
    for key, (fmt, desc) in formats.items():
        print(f"  [{key}] {fmt} - {desc}")

    while True:
        choice = input("\n请选择备份格式 [1-3]: ").strip() or "1"
        if choice in formats:
            selected = formats[choice][0]
            settings["backup_format"] = selected
            save_settings(settings)
            print(f"✓ 已保存备份格式: {selected}")
            return selected
        else:
            print("无效选择，请重试")


# ============================================================
# 文件扫描与排除
# ============================================================

def should_exclude(relative_path, exclude_patterns):
    """检查文件是否应该被排除"""
    rel_str = str(relative_path).replace("\\", "/")

    for pattern in exclude_patterns:
        # 支持目录模式 (以 / 结尾)
        if pattern.endswith("/"):
            # 检查路径中是否有匹配的目录
            parts = rel_str.split("/")
            for part in parts:
                if fnmatch(part + "/", pattern):
                    return True
        elif fnmatch(rel_str, pattern):
            return True
        # 也检查文件名部分
        filename = os.path.basename(rel_str)
        if fnmatch(filename, pattern):
            return True

    return False


def scan_config_dir(config_dir, exclude_patterns):
    """扫描配置目录，返回文件列表和哈希值"""
    config_path = Path(config_dir)
    files = {}

    if not config_path.exists():
        print(f"✗ 配置目录不存在: {config_dir}")
        return files

    for root, dirs, filenames in os.walk(config_path):
        root_path = Path(root)

        # 过滤目录（原地修改 dirs 列表以跳过）
        dirs_to_remove = []
        for d in dirs:
            rel_dir = (root_path / d).relative_to(config_path)
            if should_exclude(str(rel_dir) + "/", exclude_patterns):
                dirs_to_remove.append(d)
        for d in dirs_to_remove:
            dirs.remove(d)

        # 处理文件
        for filename in filenames:
            file_path = root_path / filename
            rel_path = file_path.relative_to(config_path)

            if should_exclude(rel_path, exclude_patterns):
                continue

            try:
                # 计算文件哈希
                file_hash = compute_file_hash(file_path)
                file_size = file_path.stat().st_size

                files[str(rel_path)] = {
                    "hash": file_hash,
                    "size": file_size,
                }
            except (OSError, PermissionError) as e:
                print(f"  跳过 {rel_path}: {e}")

    return files


def compute_file_hash(file_path, algorithm="sha256"):
    """计算文件哈希值"""
    h = hashlib.new(algorithm)
    try:
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except (OSError, PermissionError):
        return None


# ============================================================
# 变更检测
# ============================================================

def detect_changes(current_files, last_manifest):
    """对比当前文件与上次备份，检测变更"""
    if not last_manifest:
        return {
            "added": list(current_files.keys()),
            "removed": [],
            "modified": [],
            "unchanged": [],
            "has_changes": True,
        }

    current_set = set(current_files.keys())
    last_set = set(last_manifest.keys())

    added = list(current_set - last_set)
    removed = list(last_set - current_set)
    modified = []
    unchanged = []

    for path in current_set & last_set:
        if current_files[path]["hash"] != last_manifest[path].get("hash"):
            modified.append(path)
        else:
            unchanged.append(path)

    has_changes = bool(added or removed or modified)

    return {
        "added": sorted(added),
        "removed": sorted(removed),
        "modified": sorted(modified),
        "unchanged": sorted(unchanged),
        "has_changes": has_changes,
    }


# ============================================================
# 清单显示
# ============================================================

def format_size(size_bytes):
    """格式化文件大小"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def display_manifest(config_dir, files, changes, backup_dir, backup_format):
    """显示备份清单"""
    print("\n" + "=" * 60)
    print("  📋 备份清单")
    print("=" * 60)

    print(f"\n  配置目录: {config_dir}")
    print(f"  备份目标: {backup_dir}")
    print(f"  备份格式: {backup_format}")

    total_files = len(files)
    total_size = sum(f["size"] for f in files.values())

    print(f"\n  文件总数: {total_files}")
    print(f"  总大小:   {format_size(total_size)}")

    if changes:
        print(f"\n  变更状态:")
        print(f"    新增: {len(changes['added'])} 个文件")
        print(f"    删除: {len(changes['removed'])} 个文件")
        print(f"    修改: {len(changes['modified'])} 个文件")
        print(f"    未变: {len(changes['unchanged'])} 个文件")

        # 显示变更详情
        if changes["added"]:
            print(f"\n  🟢 新增文件:")
            for f in changes["added"][:10]:
                print(f"    + {f} ({format_size(files[f]['size'])})")
            if len(changes["added"]) > 10:
                print(f"    ... 还有 {len(changes['added']) - 10} 个文件")

        if changes["modified"]:
            print(f"\n  🟡 修改文件:")
            for f in changes["modified"][:10]:
                print(f"    ~ {f} ({format_size(files[f]['size'])})")
            if len(changes["modified"]) > 10:
                print(f"    ... 还有 {len(changes['modified']) - 10} 个文件")

        if changes["removed"]:
            print(f"\n  🔴 删除文件:")
            for f in changes["removed"][:10]:
                print(f"    - {f}")
            if len(changes["removed"]) > 10:
                print(f"    ... 还有 {len(changes['removed']) - 10} 个文件")

    print("\n" + "=" * 60)


def confirm_backup(changes, settings):
    """用户确认是否执行备份"""
    auto_backup = settings.get("auto_backup_no_change", True)

    if changes and not changes["has_changes"] and auto_backup:
        print("\n  ✨ 检测到无文件变更，自动执行备份...")
        return True

    while True:
        resp = input("\n是否执行备份? [Y/n] (输入 m 修改设置): ").strip().lower()
        if resp in ("", "y", "yes"):
            return True
        elif resp in ("n", "no"):
            return False
        elif resp == "m":
            modify_settings_interactive(settings)
            return None  # 重新生成清单
        else:
            print("无效输入，请重试")


def modify_settings_interactive(settings):
    """交互式修改设置"""
    while True:
        print("\n--- 修改设置 ---")
        print("  [1] 更改配置目录")
        print("  [2] 更改备份目录")
        print("  [3] 更改备份格式")
        print("  [4] 管理排除规则")
        print("  [5] 切换自动备份（无变更时）")
        print("  [0] 返回")

        choice = input("\n请选择 [0-5]: ").strip()

        if choice == "1":
            settings["config_dir"] = None
            save_settings(settings)
            confirm_config_dir(settings)
        elif choice == "2":
            settings["backup_dir"] = None
            save_settings(settings)
            confirm_backup_dir(settings)
        elif choice == "3":
            confirm_backup_format(settings)
        elif choice == "4":
            manage_excludes(settings)
        elif choice == "5":
            current = settings.get("auto_backup_no_change", True)
            settings["auto_backup_no_change"] = not current
            save_settings(settings)
            print(f"✓ 自动备份已{'开启' if not current else '关闭'}")
        elif choice == "0":
            break
        else:
            print("无效选择")


def manage_excludes(settings):
    """管理排除规则"""
    excludes = settings.get("exclude_patterns", DEFAULT_EXCLUDES.copy())

    while True:
        print(f"\n--- 排除规则（共 {len(excludes)} 条）---")
        for i, pattern in enumerate(excludes[:20], 1):
            print(f"  [{i}] {pattern}")
        if len(excludes) > 20:
            print(f"  ... 还有 {len(excludes) - 20} 条")

        print("\n  [a] 添加规则")
        print("  [d] 删除规则")
        print("  [r] 恢复默认")
        print("  [0] 返回")

        choice = input("\n请选择: ").strip().lower()

        if choice == "a":
            new_pattern = input("输入新的排除规则 (如 *.tmp 或 cache/): ").strip()
            if new_pattern:
                excludes.append(new_pattern)
                settings["exclude_patterns"] = excludes
                save_settings(settings)
                print(f"✓ 已添加规则: {new_pattern}")
        elif choice == "d":
            idx = input("输入要删除的规则编号: ").strip()
            if idx.isdigit() and 1 <= int(idx) <= len(excludes):
                removed = excludes.pop(int(idx) - 1)
                settings["exclude_patterns"] = excludes
                save_settings(settings)
                print(f"✓ 已删除规则: {removed}")
            else:
                print("无效编号")
        elif choice == "r":
            settings["exclude_patterns"] = DEFAULT_EXCLUDES.copy()
            save_settings(settings)
            print("✓ 已恢复默认排除规则")
            excludes = DEFAULT_EXCLUDES.copy()
        elif choice == "0":
            break
        else:
            print("无效选择")


# ============================================================
# 备份执行
# ============================================================

def do_backup(config_dir, backup_dir, backup_format, files, settings):
    """执行备份"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"claude-config-backup_{timestamp}"
    backup_path = Path(backup_dir)
    backup_path.mkdir(parents=True, exist_ok=True)

    print(f"\n  正在备份到: {backup_dir}")
    print(f"  备份名称: {backup_name}")

    try:
        if backup_format == "zip":
            backup_file = backup_path / f"{backup_name}.zip"
            backup_zip(config_dir, files, backup_file)
            result_path = str(backup_file)
        elif backup_format == "targz":
            backup_file = backup_path / f"{backup_name}.tar.gz"
            backup_targz(config_dir, files, backup_file)
            result_path = str(backup_file)
        elif backup_format == "copy":
            backup_folder = backup_path / backup_name
            backup_copy(config_dir, files, backup_folder)
            result_path = str(backup_folder)
        else:
            print(f"✗ 不支持的备份格式: {backup_format}")
            return False

        # 保存清单
        manifest_path = backup_path / f"{backup_name}_manifest.json"
        manifest = {
            "backup_time": datetime.now().isoformat(),
            "config_dir": config_dir,
            "backup_format": backup_format,
            "files": files,
            "file_count": len(files),
            "total_size": sum(f["size"] for f in files.values()),
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        # 更新设置
        settings["last_backup_time"] = datetime.now().isoformat()
        settings["last_backup_manifest"] = files
        save_settings(settings)

        print(f"\n  ✓ 备份完成!")
        print(f"    路径: {result_path}")
        print(f"    清单: {manifest_path}")
        return True

    except Exception as e:
        print(f"\n  ✗ 备份失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def backup_zip(config_dir, files, output_file):
    """ZIP 格式备份"""
    config_path = Path(config_dir)
    with zipfile.ZipFile(output_file, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_path, info in files.items():
            full_path = config_path / rel_path
            zf.write(full_path, arcname=rel_path)
    print(f"    - ZIP 压缩完成 ({format_file_size(output_file)})")


def backup_targz(config_dir, files, output_file):
    """tar.gz 格式备份"""
    config_path = Path(config_dir)
    with tarfile.open(output_file, "w:gz") as tf:
        for rel_path, info in files.items():
            full_path = config_path / rel_path
            tf.add(full_path, arcname=rel_path)
    print(f"    - tar.gz 压缩完成 ({format_file_size(output_file)})")


def backup_copy(config_dir, files, output_dir):
    """目录拷贝备份"""
    config_path = Path(config_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for rel_path, info in files.items():
        src = config_path / rel_path
        dst = output_dir / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    print(f"    - 目录拷贝完成 ({len(files)} 个文件)")


def format_file_size(filepath):
    """获取文件大小字符串"""
    try:
        size = filepath.stat().st_size
        return format_size(size)
    except OSError:
        return "unknown"


# ============================================================
# 状态显示
# ============================================================

def show_status(settings):
    """显示当前设置状态"""
    print("\n" + "=" * 50)
    print("  📊 Smart Claude Backup 状态")
    print("=" * 50)

    print(f"\n  配置目录:   {settings.get('config_dir') or '未设置'}")
    print(f"  备份目录:   {settings.get('backup_dir') or '未设置'}")
    print(f"  备份格式:   {settings.get('backup_format', '未设置')}")
    print(f"  排除规则:   {len(settings.get('exclude_patterns', []))} 条")
    print(f"  自动备份:   {'开启' if settings.get('auto_backup_no_change', True) else '关闭'}")

    last_time = settings.get("last_backup_time")
    if last_time:
        try:
            dt = datetime.fromisoformat(last_time)
            print(f"  上次备份:   {dt.strftime('%Y-%m-%d %H:%M:%S')}")
        except ValueError:
            print(f"  上次备份:   {last_time}")

        manifest = settings.get("last_backup_manifest")
        if manifest:
            print(f"  备份文件数: {len(manifest)} 个")
            total_size = sum(f.get("size", 0) for f in manifest.values())
            print(f"  备份大小:   {format_size(total_size)}")
    else:
        print(f"  上次备份:   从未备份")

    print(f"\n  设置文件:   {SETTINGS_FILE}")
    print("=" * 50)


# ============================================================
# 主流程
# ============================================================

def run_interactive(settings):
    """交互式备份流程"""
    print("\n🚀 Smart Claude Backup - 智能备份工具")

    # 1. 确认配置目录
    config_dir = confirm_config_dir(settings)
    if not config_dir:
        print("✗ 未指定配置目录，退出")
        return False

    # 2. 确认备份目录
    backup_dir = confirm_backup_dir(settings)
    if not backup_dir:
        print("✗ 未指定备份目录，退出")
        return False

    # 3. 确认备份格式
    backup_format = confirm_backup_format(settings)

    # 4. 扫描文件
    print("\n  正在扫描配置文件...")
    files = scan_config_dir(config_dir, settings.get("exclude_patterns", DEFAULT_EXCLUDES))
    if not files:
        print("✗ 未找到可备份的文件")
        return False
    print(f"  找到 {len(files)} 个文件")

    # 5. 变更检测
    last_manifest = settings.get("last_backup_manifest")
    changes = detect_changes(files, last_manifest)

    # 6. 显示清单并确认
    while True:
        display_manifest(config_dir, files, changes, backup_dir, backup_format)
        result = confirm_backup(changes, settings)

        if result is True:
            # 执行备份
            return do_backup(config_dir, backup_dir, backup_format, files, settings)
        elif result is False:
            print("备份已取消")
            return False
        # None 表示修改了设置，需要重新扫描
        else:
            # 重新确认必要信息
            config_dir = settings.get("config_dir") or confirm_config_dir(settings)
            backup_dir = settings.get("backup_dir") or confirm_backup_dir(settings)
            backup_format = settings.get("backup_format", "zip")

            print("\n  正在重新扫描配置文件...")
            files = scan_config_dir(config_dir, settings.get("exclude_patterns", DEFAULT_EXCLUDES))
            changes = detect_changes(files, last_manifest)


def run_backup_only(settings):
    """非交互模式：直接使用保存的设置备份"""
    config_dir = settings.get("config_dir")
    backup_dir = settings.get("backup_dir")
    backup_format = settings.get("backup_format", "zip")

    if not config_dir:
        print("✗ 未设置配置目录，请先运行 --interactive")
        return False
    if not backup_dir:
        print("✗ 未设置备份目录，请先运行 --interactive")
        return False

    print(f"配置目录: {config_dir}")
    print(f"备份目录: {backup_dir}")
    print(f"备份格式: {backup_format}")

    print("\n正在扫描文件...")
    files = scan_config_dir(config_dir, settings.get("exclude_patterns", DEFAULT_EXCLUDES))
    if not files:
        print("✗ 未找到可备份的文件")
        return False

    print(f"找到 {len(files)} 个文件")

    last_manifest = settings.get("last_backup_manifest")
    changes = detect_changes(files, last_manifest)

    if not changes["has_changes"] and settings.get("auto_backup_no_change", True):
        print("检测到无文件变更，自动执行备份...")
    else:
        print(f"变更: 新增 {len(changes['added'])} | 删除 {len(changes['removed'])} | 修改 {len(changes['modified'])}")

    return do_backup(config_dir, backup_dir, backup_format, files, settings)


def main():
    parser = argparse.ArgumentParser(
        description="Smart Claude Backup - Claude Code 配置智能备份工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --interactive          交互模式（推荐首次使用）
  %(prog)s --backup               使用已保存设置直接备份
  %(prog)s --status               查看当前设置状态
  %(prog)s --reset                重置所有设置
  %(prog)s --config-dir ~/.claude --backup-dir ~/backups --format zip
        """
    )

    parser.add_argument("--interactive", "-i", action="store_true",
                        help="交互模式运行")
    parser.add_argument("--backup", "-b", action="store_true",
                        help="使用已保存设置直接备份")
    parser.add_argument("--status", "-s", action="store_true",
                        help="显示当前设置状态")
    parser.add_argument("--reset", action="store_true",
                        help="重置所有设置")

    parser.add_argument("--config-dir", type=str,
                        help="指定 Claude Code 配置目录")
    parser.add_argument("--backup-dir", type=str,
                        help="指定备份目标目录")
    parser.add_argument("--format", "-f", type=str,
                        choices=["zip", "targz", "copy"],
                        help="备份格式 (zip/targz/copy)")
    parser.add_argument("--exclude", action="append",
                        help="添加额外排除规则（可多次使用）")

    args = parser.parse_args()

    # 加载设置
    settings = load_settings()

    # 命令行参数覆盖设置
    if args.config_dir:
        settings["config_dir"] = os.path.expanduser(args.config_dir)
    if args.backup_dir:
        settings["backup_dir"] = os.path.expanduser(args.backup_dir)
    if args.format:
        settings["backup_format"] = args.format
    if args.exclude:
        if "exclude_patterns" not in settings:
            settings["exclude_patterns"] = DEFAULT_EXCLUDES.copy()
        settings["exclude_patterns"].extend(args.exclude)

    # 保存命令行指定的设置
    if args.config_dir or args.backup_dir or args.format:
        save_settings(settings)

    # 执行操作
    if args.reset:
        reset_settings()
    elif args.status:
        show_status(settings)
    elif args.backup:
        success = run_backup_only(settings)
        sys.exit(0 if success else 1)
    elif args.interactive:
        success = run_interactive(settings)
        sys.exit(0 if success else 1)
    elif args.config_dir and args.backup_dir:
        # 提供了必要参数，直接备份
        success = run_backup_only(settings)
        sys.exit(0 if success else 1)
    else:
        # 默认显示帮助 + 状态
        parser.print_help()
        show_status(settings)


if __name__ == "__main__":
    main()
