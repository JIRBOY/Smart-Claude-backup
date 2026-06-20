# Smart Claude Backup 使用说明

## 概述

Smart Claude Backup 是一个 Claude Code 配置智能备份工具，支持自动发现配置目录、智能排除临时文件、多格式备份、变更检测和用户确认。

## 快速开始

### 首次使用（交互模式）

```bash
python scripts/claude_backup.py --interactive
```

交互模式会引导你完成：
1. 选择/指定 Claude Code 配置目录
2. 设置备份目标目录
3. 选择备份格式
4. 生成备份清单并确认
5. 执行备份

### 日常使用

首次配置完成后，直接运行：

```bash
python scripts/claude_backup.py --backup
```

系统会自动使用已保存的设置进行备份。如果没有文件变更，会自动快速备份。

## 命令行参数

| 参数 | 说明 |
|------|------|
| `-i, --interactive` | 交互模式运行 |
| `-b, --backup` | 使用已保存设置直接备份 |
| `-s, --status` | 显示当前设置状态 |
| `--reset` | 重置所有设置 |
| `--config-dir PATH` | 指定配置目录 |
| `--backup-dir PATH` | 指定备份目录 |
| `-f, --format FORMAT` | 备份格式：zip/targz/copy |
| `--exclude PATTERN` | 添加排除规则（可多次使用） |

## 备份格式

### zip（默认）
- 跨平台兼容性好
- 压缩率适中
- 可用任意解压工具打开

### targz (tar.gz)
- Unix/Linux 风格
- 压缩率较高
- 保留文件权限

### copy（目录拷贝）
- 直接复制文件
- 无需解压即可查看
- 便于对比和手动恢复

## 排除规则

默认排除以下类型的文件：

- **临时文件**: `*.tmp`, `*.temp`, `*~`, `*.swp`, `.DS_Store`, `Thumbs.db`
- **缓存文件**: `*.cache`, `cache/`, `__pycache__/`, `.cache/`
- **依赖目录**: `node_modules/`
- **日志文件**: `*.log`, `logs/`
- **锁文件**: `*.lock`
- **二进制文件**: `*.bin`, `*.exe`, `*.dll`, `*.so`, `*.dylib`
- **版本控制**: `.git/`

### 自定义排除规则

在交互模式中选择 `m` → `4` 管理排除规则，可以添加、删除或恢复默认规则。

也可以通过命令行临时添加：

```bash
python scripts/claude_backup.py --backup --exclude "*.bak" --exclude "temp/"
```

## 设置存储

所有设置保存在 `~/.smart-claude-backup/settings.json`，包括：

```json
{
  "config_dir": "/path/to/claude/config",
  "backup_dir": "/path/to/backups",
  "backup_format": "zip",
  "exclude_patterns": [...],
  "auto_backup_no_change": true,
  "last_backup_time": "2024-01-01T12:00:00",
  "last_backup_manifest": { ... }
}
```

## 变更检测原理

每次备份会计算所有文件的 SHA-256 哈希值并保存到清单中。下次备份时：

1. 重新扫描并计算哈希
2. 与上次备份清单对比
3. 识别新增、删除、修改的文件
4. 如果无变更且开启了自动备份，直接执行

## 备份输出

每次备份生成两个文件：

1. **备份文件**: `claude-config-backup_YYYYMMDD_HHMMSS.{zip|tar.gz}` 或目录
2. **清单文件**: `claude-config-backup_YYYYMMDD_HHMMSS_manifest.json`

清单文件包含备份时间、配置目录、文件列表和哈希值，可用于后续对比和验证。

## 恢复配置

### ZIP 格式恢复
```bash
unzip claude-config-backup_XXXXXXXX_XXXXXX.zip -d ~/.claude
```

### tar.gz 格式恢复
```bash
tar -xzf claude-config-backup_XXXXXXXX_XXXXXX.tar.gz -C ~/.claude
```

### 目录拷贝恢复
```bash
cp -r claude-config-backup_XXXXXXXX_XXXXXX/* ~/.claude/
```

> ⚠️ 恢复前建议先备份当前配置。

## 示例场景

### 场景1：日常快速备份
```bash
python scripts/claude_backup.py -b
```

### 场景2：检查设置状态
```bash
python scripts/claude_backup.py -s
```

### 场景3：使用不同格式备份
```bash
python scripts/claude_backup.py -b -f targz
```

### 场景4：指定不同备份位置
```bash
python scripts/claude_backup.py --backup-dir /mnt/external/claude-backups
```

### 场景5：重置所有设置重新配置
```bash
python scripts/claude_backup.py --reset
python scripts/claude_backup.py --interactive
```
