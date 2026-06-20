#!/usr/bin/env python3
"""
Claude Code Smart Backup Tool
自动查找、确认并备份 Claude Code 配置文件，支持多种备份格式，记忆用户设置。
"""

import os
import sys
import json
import hashlib
import shutil
import zipfile
import tarfile
import fnmatch
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Set


# =============================================================================
# 默认排除规则
# =============================================================================

DEFAULT_EXCLUDE_DIRS = {
    'node_modules', '__pycache__', '.git', 'venv', '.venv', 'env', '.env',
    'cache', '.cache', 'logs', 'dist', 'build', '.next', '.nuxt',
    '.terraform', '.serverless',
}

DEFAULT_EXCLUDE_FILE_PATTERNS = [
    '*.tmp', '*.temp', '*.swp', '*.swo', '*~', '.DS_Store', 'Thumbs.db',
    '*.log', '*.bak', '*.old', '*.crdownload', '.part',
    '*.pyc', '*.pyo', '*.pyd',
]

# Claude Code 配置目录常见位置（按优先级）
COMMON_CONFIG_LOCATIONS = [
    # Linux
    ('~/.config/claude', 'XDG 配置目录 (Linux)'),
    ('~/.claude', '用户主目录下 .claude (跨平台)'),
    # macOS
    ('~/Library/Application Support/Claude', 'macOS Application Support'),
    ('~/Library/Preferences/Claude', 'macOS Preferences'),
    # Windows
    ('%APPDATA%/Claude', 'Windows AppData'),
    ('%LOCALAPPDATA%/Claude', 'Windows LocalAppData'),
    ('%USERPROFILE%/.claude', 'Windows 用户目录'),
    # 其他可能位置
    ('~/snap/claude/common/.config/claude', 'Snap 安装 (Linux)'),
    ('~/.var/app/com.anthropic.claude/config/claude', 'Flatpak (Linux)'),
]


# =============================================================================
# 设置管理
# =============================================================================

def get_settings_path() -> Path:
    """获取设置文件路径（脚本同目录下）"""
    script_dir = Path(__file__).resolve().parent
    settings_dir = script_dir / '.backup_state'
    settings_dir.mkdir(exist_ok=True)
    return settings_dir / 'settings.json'


def load_settings() -> dict:
    """加载已保存的设置"""
    settings_path = get_settings_path()
    if settings_path.exists():
        with open(settings_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_settings(settings: dict):
    """保存设置"""
    settings_path = get_settings_path()
    with open(settings_path, 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


# =============================================================================
# 配置目录发现
# =============================================================================

def expand_path(p: str) -> Path:
    """展开路径中的变量和用户目录"""
    expanded = os.path.expandvars(os.path.expanduser(p))
    return Path(expanded).resolve()


def find_claude_config_dirs() -> List[Tuple[Path, str]]:
    """查找所有存在的 Claude Code 配置目录"""
    found = []
    for loc, desc in COMMON_CONFIG_LOCATIONS:
        path = expand_path(loc)
        if path.exists() and path.is_dir():
            # 检查是否包含 Claude 相关文件（作为额外验证）
            has_claude_files = any(
                f.name.lower().startswith('claude') or f.name.lower().startswith('.claude')
                or f.suffix in ['.json', '.yaml', '.yml', '.toml']
                for f in path.iterdir()
                if f.is_file()
            )
            # 如果目录非空就考虑
            if any(path.iterdir()) or has_claude_files:
                found.append((path, desc))
    
    # 去重（可能不同的路径展开后相同）
    seen = set()
    unique = []
    for path, desc in found:
        if str(path) not in seen:
            seen.add(str(path))
            unique.append((path, desc))
    
    return unique


def prompt_select_config_dir(found_dirs: List[Tuple[Path, str]]) -> Optional[Path]:
    """交互式选择配置目录"""
    if not found_dirs:
        print("⚠️  未自动找到 Claude Code 配置目录")
        print()
        user_path = input("请手动输入 Claude Code 配置目录路径（留空跳过）: ").strip()
        if user_path:
            p = expand_path(user_path)
            if p.exists() and p.is_dir():
                return p
            else:
                print(f"❌ 目录不存在: {p}")
                return None
        return None
    
    print(f"📂 发现 {len(found_dirs)} 个可能的 Claude Code 配置目录:")
    print()
    for i, (path, desc) in enumerate(found_dirs, 1):
        file_count = sum(1 for _ in path.rglob('*') if _.is_file())
        total_size = sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
        print(f"  [{i}] {path}")
        print(f"      来源: {desc}")
        print(f"      文件数: {file_count}, 大小: {format_size(total_size)}")
        print()
    
    while True:
        choice = input("请选择要备份的目录编号（或输入自定义路径，留空取消）: ").strip()
        if not choice:
            return None
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(found_dirs):
                return found_dirs[idx][0]
        # 可能是自定义路径
        p = expand_path(choice)
        if p.exists() and p.is_dir():
            return p
        print(f"无效输入: {choice}")


# =============================================================================
# 文件清单 / 排除规则
# =============================================================================

def should_exclude(
    rel_path: str,
    is_dir: bool,
    exclude_dirs: Set[str],
    exclude_patterns: List[str],
    custom_excludes: Optional[List[str]] = None,
) -> bool:
    """判断文件/目录是否应该被排除"""
    parts = Path(rel_path).parts
    
    # 检查目录名排除
    if is_dir:
        for part in parts:
            if part in exclude_dirs:
                return True
    
    # 检查文件模式排除
    for pattern in exclude_patterns:
        for part in parts:
            if fnmatch.fnmatch(part, pattern):
                return True
    
    # 自定义排除规则
    if custom_excludes:
        for pattern in custom_excludes:
            if fnmatch.fnmatch(rel_path, pattern):
                return True
            # 也对每个部分匹配
            for part in parts:
                if fnmatch.fnmatch(part, pattern):
                    return True
    
    return False


def build_manifest(
    config_dir: Path,
    exclude_dirs: Set[str],
    exclude_patterns: List[str],
    custom_excludes: Optional[List[str]] = None,
) -> Dict[str, dict]:
    """构建文件清单 (相对路径 -> 文件元数据)"""
    manifest = {}
    config_dir = config_dir.resolve()
    
    for root, dirs, files in os.walk(config_dir):
        root_path = Path(root)
        rel_root = root_path.relative_to(config_dir)
        
        # 过滤目录（原地修改 dirs 列表以避免进入被排除的目录）
        dirs_to_remove = []
        for d in dirs:
            rel_d = str(rel_root / d) if str(rel_root) != '.' else d
            if should_exclude(rel_d, True, exclude_dirs, exclude_patterns, custom_excludes):
                dirs_to_remove.append(d)
        for d in dirs_to_remove:
            dirs.remove(d)
        
        # 处理文件
        for f in files:
            file_path = root_path / f
            rel_path = str(rel_root / f) if str(rel_root) != '.' else f
            
            if should_exclude(rel_path, False, exclude_dirs, exclude_patterns, custom_excludes):
                continue
            
            try:
                stat = file_path.stat()
                manifest[rel_path] = {
                    'size': stat.st_size,
                    'mtime': stat.st_mtime,
                }
            except OSError:
                # 跳过无法读取的文件
                continue
    
    return manifest


def compute_file_hash(file_path: Path) -> str:
    """计算文件 SHA256 哈希"""
    h = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def compare_manifests(old: Dict[str, dict], new: Dict[str, dict]) -> dict:
    """比较两个清单，返回差异"""
    old_keys = set(old.keys())
    new_keys = set(new.keys())
    
    added = new_keys - old_keys
    removed = old_keys - new_keys
    modified = set()
    
    for key in old_keys & new_keys:
        if old[key]['size'] != new[key]['size'] or old[key]['mtime'] != new[key]['mtime']:
            modified.add(key)
    
    return {
        'added': sorted(added),
        'removed': sorted(removed),
        'modified': sorted(modified),
        'unchanged': sorted((old_keys & new_keys) - modified),
    }


# =============================================================================
# 备份执行
# =============================================================================

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


def get_backup_dir(target_dir: Path, backup_format: str) -> Path:
    """获取备份目标目录，确保存在"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f"claude_backup_{timestamp}"
    backup_path = target_dir / backup_name
    
    if backup_format == 'copy':
        # 目录形式
        backup_path.mkdir(parents=True, exist_ok=True)
    else:
        # zip 或 tar.gz 文件，先确保父目录存在
        target_dir.mkdir(parents=True, exist_ok=True)
    
    return backup_path


def do_backup_zip(config_dir: Path, manifest: Dict[str, dict], backup_path: Path) -> Path:
    """以 zip 格式备份"""
    zip_path = backup_path.parent / (backup_path.name + '.zip')
    config_dir = config_dir.resolve()
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for rel_path in sorted(manifest.keys()):
            file_path = config_dir / rel_path
            try:
                zf.write(file_path, arcname=rel_path)
            except OSError:
                continue
    
    return zip_path


def do_backup_tar_gz(config_dir: Path, manifest: Dict[str, dict], backup_path: Path) -> Path:
    """以 tar.gz 格式备份"""
    tar_path = backup_path.parent / (backup_path.name + '.tar.gz')
    config_dir = config_dir.resolve()
    
    with tarfile.open(tar_path, 'w:gz') as tf:
        for rel_path in sorted(manifest.keys()):
            file_path = config_dir / rel_path
            try:
                tf.add(file_path, arcname=rel_path)
            except OSError:
                continue
    
    return tar_path


def do_backup_copy(config_dir: Path, manifest: Dict[str, dict], backup_path: Path) -> Path:
    """以目录复制形式备份"""
    config_dir = config_dir.resolve()
    
    for rel_path in sorted(manifest.keys()):
        src = config_dir / rel_path
        dst = backup_path / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, dst)
        except OSError:
            continue
    
    return backup_path


def perform_backup(
    config_dir: Path,
    manifest: Dict[str, dict],
    target_dir: Path,
    backup_format: str,
) -> Path:
    """执行备份，返回备份文件/目录路径"""
    backup_path_base = get_backup_dir(target_dir, backup_format)
    
    if backup_format == 'zip':
        result = do_backup_zip(config_dir, manifest, backup_path_base)
    elif backup_format == 'tar.gz':
        result = do_backup_tar_gz(config_dir, manifest, backup_path_base)
    elif backup_format == 'copy':
        result = do_backup_copy(config_dir, manifest, backup_path_base)
    else:
        raise ValueError(f"不支持的备份格式: {backup_format}")
    
    return result


# =============================================================================
# 交互式流程
# =============================================================================

def print_settings_summary(settings: dict):
    """打印当前设置摘要"""
    print("=" * 60)
    print("📋 当前备份设置")
    print("=" * 60)
    print(f"  配置目录:   {settings.get('config_dir', '未设置')}")
    print(f"  备份目标:   {settings.get('target_dir', '未设置')}")
    print(f"  备份格式:   {settings.get('backup_format', 'zip')}")
    
    custom = settings.get('custom_excludes', [])
    if custom:
        print(f"  自定义排除: {', '.join(custom)}")
    else:
        print(f"  自定义排除: 无")
    
    print(f"  排除目录:   {', '.join(sorted(DEFAULT_EXCLUDE_DIRS))}")
    print(f"  排除模式:   {', '.join(DEFAULT_EXCLUDE_FILE_PATTERNS)}")
    print("=" * 60)


def interactive_setup(settings: dict) -> dict:
    """交互式设置向导"""
    print()
    print("🔧 首次使用 — Claude Code 智能备份设置向导")
    print("=" * 60)
    print()
    
    # 1. 查找并选择配置目录
    found = find_claude_config_dirs()
    config_dir = prompt_select_config_dir(found)
    if not config_dir:
        print("❌ 未选择配置目录，无法继续。")
        return settings
    settings['config_dir'] = str(config_dir)
    print(f"✅ 已选择配置目录: {config_dir}")
    print()
    
    # 2. 设置备份目标目录
    default_target = str(Path.home() / 'claude_backups')
    target_input = input(f"请输入备份目标目录 [默认: {default_target}]: ").strip()
    target_dir = expand_path(target_input) if target_input else Path(default_target)
    target_dir.mkdir(parents=True, exist_ok=True)
    settings['target_dir'] = str(target_dir)
    print(f"✅ 备份目标目录: {target_dir}")
    print()
    
    # 3. 选择备份格式
    print("支持的备份格式:")
    print("  [1] zip      - ZIP 压缩文件（推荐，跨平台）")
    print("  [2] tar.gz   - TAR.GZ 压缩文件（适合 Unix/Linux）")
    print("  [3] copy     - 直接复制为文件夹（方便直接查看）")
    print()
    
    while True:
        fmt_choice = input("请选择备份格式 [1/2/3，默认 1]: ").strip() or '1'
        if fmt_choice == '1':
            settings['backup_format'] = 'zip'
            break
        elif fmt_choice == '2':
            settings['backup_format'] = 'tar.gz'
            break
        elif fmt_choice == '3':
            settings['backup_format'] = 'copy'
            break
        print("无效选择，请重新输入。")
    
    print(f"✅ 备份格式: {settings['backup_format']}")
    print()
    
    # 4. 自定义排除
    custom_input = input("是否添加自定义排除模式？（用逗号分隔，留空跳过）: ").strip()
    if custom_input:
        settings['custom_excludes'] = [p.strip() for p in custom_input.split(',') if p.strip()]
    else:
        settings['custom_excludes'] = []
    
    # 保存设置
    save_settings(settings)
    print()
    print("💾 设置已保存！")
    print()
    
    return settings


def backup_flow(settings: dict, auto_confirm_no_change: bool = True) -> dict:
    """主备份流程"""
    config_dir = Path(settings['config_dir'])
    target_dir = Path(settings['target_dir'])
    backup_format = settings.get('backup_format', 'zip')
    custom_excludes = settings.get('custom_excludes', [])
    
    # 构建当前清单
    manifest = build_manifest(
        config_dir,
        DEFAULT_EXCLUDE_DIRS,
        DEFAULT_EXCLUDE_FILE_PATTERNS,
        custom_excludes,
    )
    
    total_files = len(manifest)
    total_size = sum(m['size'] for m in manifest.values())
    
    # 打印清单预览
    print_settings_summary(settings)
    print()
    print(f"📦 待备份内容预览:")
    print(f"   文件总数: {total_files}")
    print(f"   总大小:   {format_size(total_size)}")
    print()
    
    # 与上次备份比较
    last_manifest = settings.get('last_manifest', {})
    if last_manifest:
        diff = compare_manifests(last_manifest, manifest)
        added_count = len(diff['added'])
        removed_count = len(diff['removed'])
        modified_count = len(diff['modified'])
        unchanged_count = len(diff['unchanged'])
        
        has_changes = added_count > 0 or removed_count > 0 or modified_count > 0
        
        print(f"📊 与上次备份对比:")
        print(f"   新增:  {added_count} 个文件")
        print(f"   删除:  {removed_count} 个文件")
        print(f"   修改:  {modified_count} 个文件")
        print(f"   未变:  {unchanged_count} 个文件")
        print()
        
        # 展示具体变化（如果不多的话）
        if has_changes:
            if added_count <= 20 and added_count > 0:
                print("  新增文件:")
                for f in diff['added']:
                    size = manifest[f]['size']
                    print(f"    + {f} ({format_size(size)})")
                print()
            if removed_count <= 20 and removed_count > 0:
                print("  删除文件:")
                for f in diff['removed']:
                    print(f"    - {f}")
                print()
            if modified_count <= 20 and modified_count > 0:
                print("  修改文件:")
                for f in diff['modified']:
                    old_size = last_manifest[f]['size']
                    new_size = manifest[f]['size']
                    delta = new_size - old_size
                    delta_str = f"+{format_size(delta)}" if delta >= 0 else f"-{format_size(abs(delta))}"
                    print(f"    ~ {f} ({format_size(old_size)} → {format_size(new_size)}, {delta_str})")
                print()
        
        # 无变化自动备份
        if not has_changes and auto_confirm_no_change:
            print("✅ 文件无变化，自动执行备份...")
            print()
            result = perform_backup(config_dir, manifest, target_dir, backup_format)
            print(f"🎉 备份完成！备份位置: {result}")
            
            # 更新上次清单
            settings['last_manifest'] = manifest
            settings['last_backup_path'] = str(result)
            settings['last_backup_time'] = datetime.now().isoformat()
            save_settings(settings)
            return settings
        
        # 有变化，请求确认
        if has_changes:
            print("⚠️  检测到文件变化。")
            print()
            
            # 显示完整文件列表？
            show_all = input("是否查看完整文件清单？(y/N): ").strip().lower()
            if show_all == 'y':
                print()
                print("完整文件清单:")
                for f in sorted(manifest.keys()):
                    print(f"  {f}  ({format_size(manifest[f]['size'])})")
                print()
            
            # 确认选项
            print("请选择操作:")
            print("  [1] 确认并执行备份")
            print("  [2] 修改设置后再备份")
            print("  [3] 取消备份")
            print()
            
            while True:
                choice = input("请选择 [1/2/3，默认 1]: ").strip() or '1'
                if choice == '1':
                    # 执行备份
                    result = perform_backup(config_dir, manifest, target_dir, backup_format)
                    print()
                    print(f"🎉 备份完成！备份位置: {result}")
                    
                    settings['last_manifest'] = manifest
                    settings['last_backup_path'] = str(result)
                    settings['last_backup_time'] = datetime.now().isoformat()
                    save_settings(settings)
                    return settings
                
                elif choice == '2':
                    # 修改设置
                    settings = modify_settings_interactive(settings)
                    # 重新构建清单
                    manifest = build_manifest(
                        Path(settings['config_dir']),
                        DEFAULT_EXCLUDE_DIRS,
                        DEFAULT_EXCLUDE_FILE_PATTERNS,
                        settings.get('custom_excludes', []),
                    )
                    # 再次确认
                    continue_from_modified = input("设置已更新，是否立即执行备份？(Y/n): ").strip().lower()
                    if continue_from_modified != 'n':
                        result = perform_backup(
                            Path(settings['config_dir']),
                            manifest,
                            Path(settings['target_dir']),
                            settings.get('backup_format', 'zip'),
                        )
                        print()
                        print(f"🎉 备份完成！备份位置: {result}")
                        settings['last_manifest'] = manifest
                        settings['last_backup_path'] = str(result)
                        settings['last_backup_time'] = datetime.now().isoformat()
                        save_settings(settings)
                    return settings
                
                elif choice == '3':
                    print("已取消备份。")
                    return settings
                
                else:
                    print("无效选择。")
    else:
        # 首次备份
        print("ℹ️  这是首次备份，没有历史对比数据。")
        print()
        
        # 显示前 30 个文件
        print("前 30 个文件预览:")
        for i, f in enumerate(sorted(manifest.keys())[:30]):
            print(f"  {f}  ({format_size(manifest[f]['size'])})")
        if total_files > 30:
            print(f"  ... 还有 {total_files - 30} 个文件")
        print()
        
        confirm = input("确认执行备份？(Y/n): ").strip().lower()
        if confirm == 'n':
            print("已取消备份。")
            return settings
        
        result = perform_backup(config_dir, manifest, target_dir, backup_format)
        print()
        print(f"🎉 备份完成！备份位置: {result}")
        
        settings['last_manifest'] = manifest
        settings['last_backup_path'] = str(result)
        settings['last_backup_time'] = datetime.now().isoformat()
        save_settings(settings)
    
    return settings


def modify_settings_interactive(settings: dict) -> dict:
    """交互式修改设置"""
    while True:
        print()
        print("🔧 修改设置")
        print("-" * 40)
        print(f"  [1] 配置目录:   {settings.get('config_dir', '未设置')}")
        print(f"  [2] 备份目标:   {settings.get('target_dir', '未设置')}")
        print(f"  [3] 备份格式:   {settings.get('backup_format', 'zip')}")
        print(f"  [4] 自定义排除: {', '.join(settings.get('custom_excludes', [])) or '无'}")
        print(f"  [5] 返回")
        print()
        
        choice = input("请选择要修改的项 [1-5]: ").strip()
        
        if choice == '1':
            found = find_claude_config_dirs()
            # 加上当前路径
            current = settings.get('config_dir', '')
            if current and Path(current).exists():
                found.insert(0, (Path(current), '当前设置'))
            config_dir = prompt_select_config_dir(found)
            if config_dir:
                settings['config_dir'] = str(config_dir)
                print(f"✅ 已更新配置目录: {config_dir}")
        
        elif choice == '2':
            target_input = input(f"当前: {settings.get('target_dir', '')}\n请输入新的备份目标目录: ").strip()
            if target_input:
                target_dir = expand_path(target_input)
                target_dir.mkdir(parents=True, exist_ok=True)
                settings['target_dir'] = str(target_dir)
                print(f"✅ 已更新备份目标: {target_dir}")
        
        elif choice == '3':
            print("  [1] zip")
            print("  [2] tar.gz")
            print("  [3] copy")
            fmt_choice = input("请选择新的备份格式: ").strip()
            fmt_map = {'1': 'zip', '2': 'tar.gz', '3': 'copy'}
            if fmt_choice in fmt_map:
                settings['backup_format'] = fmt_map[fmt_choice]
                print(f"✅ 已更新备份格式: {settings['backup_format']}")
        
        elif choice == '4':
            current = ', '.join(settings.get('custom_excludes', []))
            print(f"当前自定义排除: {current or '无'}")
            new_excludes = input("请输入新的自定义排除模式（逗号分隔，留空清除）: ").strip()
            if new_excludes:
                settings['custom_excludes'] = [p.strip() for p in new_excludes.split(',') if p.strip()]
            else:
                settings['custom_excludes'] = []
            print(f"✅ 已更新自定义排除规则")
        
        elif choice == '5':
            break
        
        else:
            print("无效选择。")
    
    save_settings(settings)
    return settings


def show_history(settings: dict):
    """显示备份历史"""
    target_dir = Path(settings.get('target_dir', ''))
    if not target_dir or not target_dir.exists():
        print("❌ 备份目标目录未设置或不存在。")
        return
    
    print(f"📜 备份历史 (目标目录: {target_dir})")
    print("-" * 60)
    
    backups = []
    for item in target_dir.iterdir():
        if item.name.startswith('claude_backup_'):
            try:
                stat = item.stat()
                size = sum(f.stat().st_size for f in item.rglob('*') if f.is_file()) if item.is_dir() else stat.st_size
                backups.append((item, stat.st_mtime, size))
            except OSError:
                continue
    
    if not backups:
        print("  暂无备份记录")
        return
    
    backups.sort(key=lambda x: x[1], reverse=True)
    
    for i, (path, mtime, size) in enumerate(backups[:20], 1):
        dt = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
        type_str = "文件夹" if path.is_dir() else path.suffix.lstrip('.')
        print(f"  [{i}] {path.name}")
        print(f"      时间: {dt} | 大小: {format_size(size)} | 格式: {type_str}")
        print()
    
    # 显示上次备份信息
    last_time = settings.get('last_backup_time')
    last_path = settings.get('last_backup_path')
    if last_time and last_path:
        print("-" * 60)
        print(f"  上次成功备份: {datetime.fromisoformat(last_time).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  备份位置: {last_path}")


# =============================================================================
# 命令行入口
# =============================================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Claude Code 智能备份工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python smart_backup.py              # 交互式备份（推荐）
  python smart_backup.py --setup      # 重新运行设置向导
  python smart_backup.py --settings   # 查看当前设置
  python smart_backup.py --history    # 查看备份历史
  python smart_backup.py --auto       # 无交互自动备份（仅当无变化或首次时静默备份）
        """
    )
    parser.add_argument('--setup', action='store_true', help='重新运行设置向导')
    parser.add_argument('--settings', action='store_true', help='查看当前设置')
    parser.add_argument('--history', action='store_true', help='查看备份历史')
    parser.add_argument('--auto', action='store_true', help='自动模式（无交互）')
    parser.add_argument('--config-dir', type=str, help='指定配置目录（覆盖设置）')
    parser.add_argument('--target-dir', type=str, help='指定备份目标目录（覆盖设置）')
    parser.add_argument('--format', type=str, choices=['zip', 'tar.gz', 'copy'],
                        help='指定备份格式（覆盖设置）')
    parser.add_argument('--exclude', type=str, help='额外排除模式（逗号分隔）')
    
    args = parser.parse_args()
    
    # 加载设置
    settings = load_settings()
    
    # 命令行参数覆盖
    if args.config_dir:
        settings['config_dir'] = str(expand_path(args.config_dir))
    if args.target_dir:
        settings['target_dir'] = str(expand_path(args.target_dir))
    if args.format:
        settings['backup_format'] = args.format
    if args.exclude:
        extra = [p.strip() for p in args.exclude.split(',') if p.strip()]
        current = settings.get('custom_excludes', [])
        settings['custom_excludes'] = list(set(current + extra))
    
    # 查看设置
    if args.settings:
        print_settings_summary(settings)
        last_time = settings.get('last_backup_time')
        if last_time:
            print(f"  上次备份:   {datetime.fromisoformat(last_time).strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"  备份路径:   {settings.get('last_backup_path', 'N/A')}")
        return
    
    # 查看历史
    if args.history:
        show_history(settings)
        return
    
    # 运行设置向导（首次使用或显式指定）
    if args.setup or 'config_dir' not in settings:
        settings = interactive_setup(settings)
        if 'config_dir' not in settings:
            print("设置未完成，退出。")
            sys.exit(1)
    
    # 验证配置目录
    config_dir = Path(settings.get('config_dir', ''))
    if not config_dir.exists() or not config_dir.is_dir():
        print(f"❌ 配置目录不存在: {config_dir}")
        print("请运行 --setup 重新配置。")
        sys.exit(1)
    
    # 自动模式
    if args.auto:
        manifest = build_manifest(
            config_dir,
            DEFAULT_EXCLUDE_DIRS,
            DEFAULT_EXCLUDE_FILE_PATTERNS,
            settings.get('custom_excludes', []),
        )
        target_dir = Path(settings['target_dir'])
        backup_format = settings.get('backup_format', 'zip')
        
        result = perform_backup(config_dir, manifest, target_dir, backup_format)
        print(f"自动备份完成: {result}")
        
        settings['last_manifest'] = manifest
        settings['last_backup_path'] = str(result)
        settings['last_backup_time'] = datetime.now().isoformat()
        save_settings(settings)
        return
    
    # 交互式备份
    settings = backup_flow(settings)


if __name__ == '__main__':
    main()
