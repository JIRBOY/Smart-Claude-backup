---
name: smart-claude-backup
description: "Smart backup skill for Claude Code CLI config: auto-detect config folder, remember settings, exclude temp/dependency files, support multiple backup formats, manifest-based change detection with user confirmation."
metadata:
  version: "2.0.0"
  author: "Synthesized from granite, eclipse, helix, falcon"
  category: "tools"
  tags: ["backup", "claude-code", "config", "cli"]
allowed-tools:
  - exec
  - read
  - write
  - edit
---

# Smart Claude Backup

智能备份 Claude Code CLI 配置文件的技能。自动发现配置目录，智能排除临时/依赖文件，支持多种备份格式，检测变更并交互式确认，自动记忆用户设置。

## 何时使用

- 用户要求备份 Claude Code 配置/设置
- 定期备份 Claude Code 配置
- 迁移 Claude Code 设置到新机器前
- 重大配置修改前创建快照
- 对比配置变化

## 核心脚本

主脚本：`scripts/backup.py`（Python 3.7+，无第三方依赖）

## 使用方式

### 交互式备份（推荐首次使用）

```bash
python Smart-Claude-backup/scripts/backup.py --interactive
```

首次运行会启动设置向导：
1. 自动扫描系统中 Claude Code 配置目录，列出候选供选择
2. 设置备份目标目录（默认：`~/claude_backups`）
3. 选择备份格式（zip / tar.gz / copy）
4. 可选添加自定义排除规则

之后每次运行：
- 构建当前文件清单
- 与上次备份对比，显示新增/删除/修改的文件
- **无变化** -> 自动执行备份
- **有变化** -> 显示变更详情，由用户确认后备份，或修改设置后再备份

### 常用命令

| 命令 | 说明 |
|------|------|
| `python backup.py --interactive` | 交互式备份（推荐） |
| `python backup.py --backup` | 使用已保存设置直接备份 |
| `python backup.py --list` | 只列出文件清单，不备份 |
| `python backup.py --status` | 查看当前设置和备份历史 |
| `python backup.py --config` | 修改设置 |
| `python backup.py --reset` | 重置所有设置 |

### 参数覆盖

可临时覆盖保存的设置：
- `--config-dir PATH` -- 指定配置目录
- `--backup-dir PATH` -- 指定备份目标目录
- `--format zip|tar.gz|copy` -- 指定备份格式
- `--exclude PATTERN` -- 额外排除规则（可多次使用）
- `--yes` -- 跳过确认直接备份

## 自动排除规则

默认排除以下内容（无需用户配置）：

**目录**：`node_modules`, `__pycache__`, `.git`, `.venv`, `venv`, `env`, `.env`, `cache`, `.cache`, `logs`, `dist`, `build`, `.next`, `.nuxt`, `.terraform`, `.serverless`, `tmp`

**文件模式**：`*.tmp`, `*.temp`, `*.swp`, `*.swo`, `*~`, `.DS_Store`, `Thumbs.db`, `desktop.ini`, `*.log`, `*.bak`, `*.old`, `*.crdownload`, `*.pyc`, `*.pyo`, `*.pyd`, `*.lock`, `*.bin`, `*.exe`, `*.dll`

用户可通过设置向导或 `--exclude` 添加自定义排除规则，也支持增量修改：`+pattern` 追加，`-pattern` 移除。

## 设置存储位置

设置保存在用户主目录：`~/.smart-claude-backup/settings.json`

包含：
- `config_dir` -- Claude Code 配置目录路径
- `backup_dir` -- 备份目标目录
- `backup_format` -- 备份格式
- `exclude_patterns` -- 排除规则列表
- `auto_backup_no_change` -- 无变化时是否自动备份
- `backup_history` -- 最近 20 条备份历史
- `last_manifest` -- 上次备份的文件哈希清单

## 备份文件命名

备份文件/目录命名格式：`claude-config-backup_YYYYMMDD_HHMMSS.<ext>`

## 配置目录搜索路径

脚本自动搜索以下位置（按优先级），也支持环境变量 `CLAUDE_CONFIG_DIR` 和 `CLAUDE_HOME`：

- Linux/macOS: `~/.claude`, `~/.config/claude`, `~/.config/claude-code`
- Windows: `%APPDATA%/Claude`, `%APPDATA%/claude-code`, `%LOCALAPPDATA%/Claude`, `%USERPROFILE%/.claude`
- 当前目录: `./.claude`

未找到时支持手动输入路径。

## 变更检测

使用 SHA256 树哈希（tree hash）检测变更，比较文件路径和内容，确保变更检测准确。

## 备份历史

自动保留最近 20 条备份历史，包含时间戳、备份路径、文件数、总大小、树哈希值等信息，可通过 `--status` 查看。
