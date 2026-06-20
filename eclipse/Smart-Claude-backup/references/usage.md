# Smart Claude Backup - 使用说明

## 目录
- [安装与运行](#安装与运行)
- [命令行参数](#命令行参数)
- [交互式操作](#交互式操作)
- [设置管理](#设置管理)
- [定时备份](#定时备份)
- [恢复备份](#恢复备份)
- [排除规则说明](#排除规则说明)
- [常见问题](#常见问题)

---

## 安装与运行

### 环境要求
- Python 3.7+
- 标准库即可，无需额外依赖

### 运行方式

```bash
# 进入项目目录
cd Smart-Claude-backup

# 交互式备份（推荐首次使用）
python3 scripts/claude_backup.py
```

---

## 命令行参数

| 参数 | 说明 |
|------|------|
| `--auto` | 全自动模式，无交互，直接执行备份 |
| `--list` | 只列出待备份文件清单，不执行备份 |
| `--config` | 只打开设置菜单，修改配置 |
| `--format <fmt>` | 指定备份格式: `zip`, `tar.gz`, `dir` |
| `--config-dir <path>` | 指定 Claude 配置目录（临时覆盖） |
| `--backup-dir <path>` | 指定备份输出目录（临时覆盖） |
| `--settings <path>` | 指定设置文件路径 |

### 示例

```bash
# 全自动备份，适合 cron 定时任务
python3 scripts/claude_backup.py --auto

# 查看当前会备份哪些文件
python3 scripts/claude_backup.py --list

# 使用 tar.gz 格式备份
python3 scripts/claude_backup.py --format tar.gz

# 指定自定义配置目录
python3 scripts/claude_backup.py --config-dir ~/my-custom-claude

# 单独修改设置
python3 scripts/claude_backup.py --config
```

---

## 交互式操作

首次运行会引导你完成初始设置：

1. **配置目录确认**
   - 自动扫描常见位置
   - 找到后询问是否使用
   - 也可手动输入路径

2. **备份目录设置**
   - 默认 `~/claude_backups`
   - 可自定义任意路径

3. **变更检测**
   - 显示新增/删除/修改的文件
   - 无变化时提示

4. **确认菜单**
   - `Y` / 回车 - 确认备份
   - `n` / `q` - 取消
   - `e` - 修改设置
   - `l` - 查看完整文件清单

---

## 设置管理

在确认菜单按 `e` 或运行 `--config` 进入设置菜单：

### 1. 修改配置目录路径
更改要备份的 Claude Code 配置目录。

### 2. 修改备份目录路径
更改备份文件保存位置。

### 3. 修改备份格式
切换 `zip` / `tar.gz` / `dir` 三种格式。

### 4. 管理排除规则
- `a` - 添加新的排除规则
- `d <编号>` - 删除指定规则
- `r` - 重置为默认规则
- `b` - 返回

### 5. 切换无变化自动备份
- 开启：配置无变化时自动跳过确认直接备份
- 关闭：每次都需要手动确认

---

## 定时备份

### Linux / macOS (cron)

每天凌晨 2 点自动备份：

```bash
# 编辑 crontab
crontab -e

# 添加以下行（替换为实际路径）
0 2 * * * /usr/bin/python3 /path/to/Smart-Claude-backup/scripts/claude_backup.py --auto >> /path/to/backup.log 2>&1
```

### Windows (任务计划程序)

1. 打开「任务计划程序」
2. 创建基本任务
3. 触发器：选择每日时间
4. 操作：启动程序
   - 程序: `python.exe`
   - 参数: `C:\path\to\Smart-Claude-backup\scripts\claude_backup.py --auto`

---

## 恢复备份

### zip 格式
```bash
# 解压到临时目录查看
unzip claude_backup_YYYYMMDD_HHMMSS.zip -d /tmp/claude_restore

# 直接覆盖配置目录（注意先备份当前配置！）
unzip claude_backup_YYYYMMDD_HHMMSS.zip -d ~/.config/claude
```

### tar.gz 格式
```bash
# 查看内容
tar tzf claude_backup_YYYYMMDD_HHMMSS.tar.gz

# 解压恢复
tar xzf claude_backup_YYYYMMDD_HHMMSS.tar.gz -C ~/.config/claude
```

### dir 格式
直接复制文件即可：
```bash
cp -r claude_backup_YYYYMMDD_HHMMSS/* ~/.config/claude/
```

> ⚠️ **恢复前建议先备份当前配置，避免覆盖丢失数据。**

---

## 排除规则说明

支持类似 .gitignore 的简单模式匹配：

| 规则示例 | 说明 |
|---------|------|
| `*.tmp` | 匹配所有 .tmp 后缀的文件 |
| `*.log` | 匹配所有 .log 后缀的文件 |
| `node_modules` | 匹配名为 node_modules 的文件或目录 |
| `cache/` | 以 `/` 结尾，只匹配目录 |
| `.DS_Store` | 匹配特定文件名 |
| `__pycache__` | 匹配 Python 缓存目录 |

匹配规则：
- 不区分大小写
- 支持 `*` (任意字符) 和 `?` (单个字符) 通配符
- 对路径中的每一段都进行匹配

---

## 备份文件结构

每次备份生成的文件包含：

```
claude_backup_20260620_084700.zip
├── settings.json          # 你的配置文件
├── conversations/         # 对话历史
├── ...                    # 其他配置
└── backup_manifest.json   # 备份清单（自动生成）
```

`backup_manifest.json` 包含：
- 备份时间
- 源目录
- 文件列表及大小、MD5 哈希
- 目录树总哈希（用于变更检测）

---

## 设置文件格式

设置保存在 `scripts/backup_settings.json`：

```json
{
  "claude_config_dir": "/home/user/.config/claude",
  "backup_dir": "/home/user/claude_backups",
  "backup_format": "zip",
  "exclude_patterns": ["*.tmp", "node_modules", "..."],
  "auto_backup_unchanged": true,
  "last_backup_time": "2026-06-20T08:47:00",
  "last_backup_hash": "abc123...",
  "backup_history": [
    {
      "timestamp": "2026-06-20T08:47:00",
      "backup_path": ".../claude_backup_20260620_084700.zip",
      "file_count": 42,
      "total_size": 1234567,
      "has_changes": true
    }
  ]
}
```

---

## 常见问题

### Q: 找不到 Claude Code 配置目录怎么办？
A: 运行 `python3 scripts/claude_backup.py --config` 手动指定路径。
   也可以设置环境变量 `export CLAUDE_CONFIG_DIR=/path/to/claude`。

### Q: 备份越来越多占空间？
A: 可以定期清理旧的备份文件，只保留最近几次。
   设置中保留最近 20 条历史记录，但实际备份文件需要手动清理。

### Q: 可以备份多个 Claude 配置吗？
A: 可以使用 `--settings` 参数指定不同的设置文件，每个配置对应一份设置：
   ```bash
   python3 claude_backup.py --settings ~/.backup_profile1.json
   python3 claude_backup.py --settings ~/.backup_profile2.json
   ```

### Q: 如何验证备份完整性？
A: 每次备份生成的 `backup_manifest.json` 包含所有文件的 MD5。
   可以解压后对比文件哈希来验证完整性。

### Q: 支持增量备份吗？
A: 当前版本是完整备份，但有变更检测功能。
   无变化时可以选择不重复备份（自动模式下会正常创建，但内容相同）。
