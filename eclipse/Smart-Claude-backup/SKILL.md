---
name: smart-claude-backup
description: "智能备份 Claude Code CLI 配置，自动查找配置目录、排除临时文件、检测变更、记忆设置。"
metadata:
  version: "1.0.0"
  author: "Fable"
  category: "tools"
  tags: ["backup", "claude-code", "config", "cli"]
allowed-tools:
  - exec
  - read
  - write
  - edit
---

# Smart Claude Backup

Claude Code CLI 智能备份工具。自动查找配置目录，智能排除临时/依赖文件，检测变更，记忆用户设置。

## 何时使用

- 用户要求备份 Claude Code 配置
- 需要迁移 Claude Code 设置到另一台机器
- 定期备份对话历史、自定义指令、API 配置等
- 对比配置变化

## 快速开始

```bash
# 交互式备份 (推荐首次使用)
python3 Smart-Claude-backup/scripts/claude_backup.py

# 全自动模式 (适合定时任务)
python3 Smart-Claude-backup/scripts/claude_backup.py --auto

# 只查看文件清单
python3 Smart-Claude-backup/scripts/claude_backup.py --list

# 修改设置
python3 Smart-Claude-backup/scripts/claude_backup.py --config
```

## 核心能力

### 1. 自动查找配置目录
自动扫描以下位置查找 Claude Code 配置：
- macOS: `~/Library/Application Support/Claude`, `~/.claude`
- Linux: `~/.config/claude`, `~/.claude`
- Windows: `%APPDATA%/Claude`, `%USERPROFILE%/.claude`
- 环境变量 `CLAUDE_CONFIG_DIR`, `CLAUDE_HOME`

首次运行时会确认找到的目录，也可手动指定。

### 2. 智能排除
默认排除以下内容，可自定义：
- 临时文件: `*.tmp`, `*.swp`, `.DS_Store` 等
- 依赖目录: `node_modules`, `__pycache__`, `.venv` 等
- 缓存日志: `.cache`, `*.log`, `logs/` 等
- 构建产物: `dist/`, `build/` 等

### 3. 备份格式
支持三种格式：
- **zip** - 默认，跨平台通用，压缩率适中
- **tar.gz** - Unix 风格，保留权限信息
- **dir** - 直接目录复制，方便查看和比对

### 4. 变更检测
每次备份自动与上次对比：
- 🆕 新增文件
- 🗑️ 删除文件
- ✏️ 修改文件

无变化时可设置自动跳过确认。

### 5. 设置记忆
所有配置保存在脚本同目录的 `backup_settings.json`：
- 配置目录路径
- 备份目标目录
- 备份格式
- 排除规则列表
- 自动备份开关
- 最近 20 条备份历史

## 交互流程

首次运行引导：
1. 自动扫描配置目录 → 确认或手动输入
2. 设置备份目标目录 → 默认 `~/claude_backups`
3. 扫描文件并显示清单
4. 检测与上次备份的差异
5. 用户确认 → 执行备份
6. 保存设置和历史记录

随时可在确认阶段按 `e` 修改设置，按 `l` 查看完整清单。

## 脚本位置

主脚本: `scripts/claude_backup.py`
设置文件: `scripts/backup_settings.json` (运行后生成)

详细用法见 `references/usage.md`。
