---
name: smart-claude-backup
description: "智能备份 Claude Code 配置文件，自动查找配置目录、排除临时文件和依赖、多格式备份、变更检测与确认、记忆设置。"
---

# Smart Claude Backup

智能备份 Claude Code 配置文件的技能。自动发现配置目录，排除临时/依赖文件，支持多种备份格式，检测变更并交互式确认，自动记忆用户设置。

## 何时使用

- 用户要求备份 Claude Code 配置/设置
- 定期备份 Claude Code 配置
- 迁移 Claude Code 设置到新机器前
- 重大配置修改前创建快照

## 核心脚本

主脚本：`scripts/smart_backup.py`（Python 3，无第三方依赖）

## 使用方式

### 交互式备份（推荐）

```bash
python Smart-Claude-backup/scripts/smart_backup.py
```

首次运行会启动设置向导：
1. 自动扫描系统中 Claude Code 配置目录，列出候选供选择
2. 设置备份目标目录
3. 选择备份格式（zip / tar.gz / 目录复制）
4. 可选添加自定义排除规则

之后每次运行：
- 构建当前文件清单
- 与上次备份对比，显示新增/删除/修改的文件
- **无变化** → 自动执行备份
- **有变化** → 显示变更详情，由用户确认后备份，或修改设置后再备份

### 常用命令

| 命令 | 说明 |
|------|------|
| `python smart_backup.py` | 交互式备份 |
| `python smart_backup.py --setup` | 重新运行设置向导 |
| `python smart_backup.py --settings` | 查看当前保存的设置 |
| `python smart_backup.py --history` | 查看备份历史 |
| `python smart_backup.py --auto` | 自动模式，无需交互直接备份 |

### 参数覆盖

可临时覆盖保存的设置：
- `--config-dir PATH` — 指定配置目录
- `--target-dir PATH` — 指定备份目标目录
- `--format zip|tar.gz|copy` — 指定备份格式
- `--exclude PATTERN1,PATTERN2` — 额外排除模式

## 自动排除规则

默认排除以下内容（无需用户配置）：

**目录**：`node_modules`, `__pycache__`, `.git`, `venv`, `.venv`, `env`, `.env`, `cache`, `.cache`, `logs`, `dist`, `build`, `.next`, `.nuxt`, `.terraform`, `.serverless`

**文件模式**：`*.tmp`, `*.temp`, `*.swp`, `*.swo`, `*~`, `.DS_Store`, `Thumbs.db`, `*.log`, `*.bak`, `*.old`, `*.crdownload`, `*.pyc`, `*.pyo`, `*.pyd`

用户可通过 `--exclude` 或设置向导添加自定义排除规则。

## 设置存储位置

设置保存在 `scripts/.backup_state/settings.json`，与脚本同目录，包含：
- `config_dir` — Claude Code 配置目录路径
- `target_dir` — 备份目标目录
- `backup_format` — 备份格式
- `custom_excludes` — 自定义排除规则
- `last_manifest` — 上次备份的文件清单（用于变更检测）
- `last_backup_path` — 上次备份文件路径
- `last_backup_time` — 上次备份时间

## 备份文件命名

备份文件/目录命名格式：`claude_backup_YYYYMMDD_HHMMSS`

## 配置目录搜索路径

脚本自动搜索以下位置（按优先级）：

- Linux: `~/.config/claude`, `~/.claude`, snap / flatpak 安装路径
- macOS: `~/Library/Application Support/Claude`, `~/Library/Preferences/Claude`
- Windows: `%APPDATA%/Claude`, `%LOCALAPPDATA%/Claude`, `%USERPROFILE%/.claude`

未找到时支持手动输入路径。
