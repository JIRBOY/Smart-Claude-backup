---
name: smart-claude-backup
description: "Smart backup skill for Claude Code config: auto-detect config folder, remember settings, exclude temp/dependency files, support multiple backup formats, manifest-based change detection with user confirmation."
---

# Smart Claude Backup

智能备份 Claude Code 配置文件的技能。自动查找配置目录、记忆用户设置、智能排除临时/依赖文件、支持多种备份格式、清单式变更确认。

## 快速开始

```bash
python scripts/claude_backup.py --interactive
```

## 核心功能

- **自动配置发现**：扫描常见 Claude Code 配置路径，用户确认后记忆
- **智能排除**：自动排除临时文件、依赖目录、缓存、日志等
- **多格式备份**：支持 zip / tar.gz / 目录拷贝 三种格式
- **清单确认**：每次备份前生成文件清单，用户确认后执行
- **变更检测**：对比上次备份哈希，无变化自动备份（可配置）
- **设置记忆**：所有用户偏好自动保存，下次直接使用

## 工作流

1. 首次运行 → 自动扫描可能的 Claude Code 配置目录
2. 列出候选目录 → 用户确认正确路径
3. 生成备份清单（含文件数、大小、变更状态）→ 用户确认
4. 执行备份 → 记录备份信息和文件哈希
5. 下次运行 → 自动检测变更，无变化快速备份，有变化提示用户

## 脚本位置

- 主脚本：`scripts/claude_backup.py`
- 详细用法：`references/usage.md`

## 常用命令

```bash
# 交互模式（推荐）
python scripts/claude_backup.py --interactive

# 直接备份（使用已保存的设置）
python scripts/claude_backup.py --backup

# 指定配置目录和备份目标
python scripts/claude_backup.py --config-dir ~/.claude --backup-dir ~/backups --format zip

# 查看当前设置
python scripts/claude_backup.py --status

# 重置所有设置
python scripts/claude_backup.py --reset
```

## 配置文件位置

设置保存在：`~/.smart-claude-backup/settings.json`
