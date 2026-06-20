# Smart Claude Backup

智能备份 [Claude Code CLI](https://claude.ai/code) 配置文件的技能。

自动发现配置目录，智能排除临时/依赖文件，支持多种备份格式，检测变更并交互式确认，自动记忆用户设置。

## 功能特性

- **自动配置发现** — 扫描常见 Claude Code 配置路径，首次使用时引导确认
- **智能排除** — 自动排除临时文件、依赖目录、缓存、日志等 38 种规则
- **多格式备份** — 支持 `zip` / `tar.gz` / 目录复制 三种格式
- **清单确认** — 每次备份前生成文件清单，分类显示新增/删除/修改/未变文件
- **变更检测** — 基于 SHA256 树哈希，无变化时自动备份
- **设置记忆** — 所有配置自动保存到 `~/.smart-claude-backup/settings.json`
- **备份历史** — 自动保留最近 20 条备份记录
- **Windows 兼容** — 无 emoji 字符，默认控制台可直接运行

## 快速开始

```bash
# 交互式备份（首次使用推荐）
python Smart-Claude-backup/scripts/backup.py --interactive

# 使用已保存设置直接备份
python Smart-Claude-backup/scripts/backup.py --backup

# 只查看文件清单
python Smart-Claude-backup/scripts/backup.py --list

# 查看当前设置和备份历史
python Smart-Claude-backup/scripts/backup.py --status
```

## 命令说明

| 命令 | 说明 |
|------|------|
| `--interactive`, `-i` | 交互式模式，引导完成配置和备份 |
| `--backup`, `-b` | 使用已保存设置直接备份 |
| `--list` | 只列出文件清单，不执行备份 |
| `--status`, `-s` | 显示当前设置和备份历史 |
| `--config` | 交互式修改设置 |
| `--reset` | 重置所有设置 |
| `--yes` | 跳过确认直接备份 |

### 参数覆盖

可临时覆盖已保存的设置：

```bash
python scripts/backup.py \
  --config-dir ~/.claude \
  --backup-dir ~/backups \
  --format zip \
  --exclude "*.secret" \
  --yes
```

## 备份格式

| 格式 | 说明 |
|------|------|
| `zip` | 默认，跨平台兼容，压缩率适中 |
| `tar.gz` | Unix 风格，保留权限信息 |
| `copy` | 直接复制为文件夹，便于直接查看 |

备份文件命名：`claude-config-backup_YYYYMMDD_HHMMSS.<ext>`

## 配置目录搜索顺序

支持环境变量 `CLAUDE_CONFIG_DIR` 和 `CLAUDE_HOME`：

- **Linux/macOS**: `~/.claude`, `~/.config/claude`, `~/.config/claude-code`
- **Windows**: `%APPDATA%/Claude`, `%LOCALAPPDATA%/Claude`, `%USERPROFILE%/.claude`
- **当前目录**: `./.claude`

## 默认排除规则

**目录**: `node_modules`, `__pycache__`, `.git`, `.venv`, `venv`, `env`, `.env`, `cache`, `.cache`, `logs`, `dist`, `build`, `.next`, `.nuxt`, `.terraform`, `.serverless`, `tmp`

**文件**: `*.tmp`, `*.temp`, `*.swp`, `*.swo`, `*~`, `.DS_Store`, `Thumbs.db`, `desktop.ini`, `*.log`, `*.bak`, `*.old`, `*.crdownload`, `*.pyc`, `*.pyo`, `*.pyd`, `*.lock`, `*.bin`, `*.exe`, `*.dll`

可通过交互式设置或 `--exclude` 参数添加自定义规则。

## 要求

- Python 3.7+
- 无第三方依赖

## 许可证

MIT
