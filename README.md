# PapersAutoDownloader (IEEE Xplore)

基于 Selenium 的 IEEE Xplore 论文自动下载工具。

适用于拥有 **授权访问** （个人订阅、机构访问等）的用户，通过模拟真实浏览器行为批量下载论文。

## 功能特性

- 支持 Edge / Chrome 浏览器（Linux/macOS 推荐 Chrome）
- 多种登录方式：手动登录、凭证登录、复用已登录的浏览器
- **连接已运行的浏览器**（推荐）：复用已登录的 Chrome/Edge 会话
- 支持关键词搜索或直接使用 IEEE 搜索结果 URL
- 自动分页下载，支持断点续传
- **智能跳过无权限论文**：自动检测并跳过无访问权限的论文
- 下载失败自动重试（最多 3 次）

## 安装

```bash
pip install -r requirements.txt
```

## 快速开始

### 方式 1：连接已运行的浏览器（推荐 ⭐）

这是最稳定的方式，可以复用已登录的浏览器 cookies。

**步骤 1：关闭浏览器，然后用调试模式启动**

<details>
<summary><b>Windows - Chrome (PowerShell)</b></summary>

```powershell
# 先关闭所有 Chrome
taskkill /F /IM chrome.exe

# 用调试模式启动（指定独立的用户数据目录避免冲突）
Start-Process "C:\Program Files\Google\Chrome\Application\chrome.exe" -ArgumentList "--remote-debugging-port=9222", "--user-data-dir=C:\selenium_chrome_profile"
```
</details>

<details>
<summary><b>Windows - Edge (PowerShell)</b></summary>

```powershell
# 先关闭所有 Edge
taskkill /F /IM msedge.exe

# 用调试模式启动
Start-Process "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" -ArgumentList "--remote-debugging-port=9222", "--user-data-dir=C:\selenium_edge_profile"
```
</details>

<details>
<summary><b>Linux - Chrome</b></summary>

```bash
# 先关闭所有 Chrome
pkill -f chrome

# 用调试模式启动
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/selenium_chrome_profile &
```
</details>

<details>
<summary><b>macOS - Chrome</b></summary>

```bash
# 先关闭所有 Chrome
pkill -f "Google Chrome"

# 用调试模式启动
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --user-data-dir=/tmp/selenium_chrome_profile &
```
</details>

**步骤 2：在浏览器中登录 IEEE Xplore**

访问 https://ieeexplore.ieee.org 并登录你的账号。

**步骤 3：运行下载工具**

```bash
# Chrome
python -m src --query "deep learning" --debugger-address "127.0.0.1:9222" --browser chrome --download-dir ./downloads --max-results 10 -v

# Edge
python -m src --query "deep learning" --debugger-address "127.0.0.1:9222" --browser edge --download-dir ./downloads --max-results 10 -v
```

### 方式 2：使用 IEEE 搜索结果 URL

适合需要复杂筛选条件的场景。

1. 在浏览器中打开 IEEE Xplore，搜索并应用各种筛选条件
2. 复制地址栏的 URL（包含 `searchresult.jsp`）
3. 运行：

```bash
python -m src --search-url "https://ieeexplore.ieee.org/search/searchresult.jsp?queryText=..." --debugger-address "127.0.0.1:9222" --browser chrome --download-dir ./downloads
```

### 方式 3：手动登录模式

启动新浏览器窗口，手动登录后继续下载。

```bash
python -m src --query "graph neural network" --year-from 2022 --year-to 2025 --download-dir ./downloads
```

浏览器窗口会打开，登录后回到终端按 Enter 继续。

### 方式 4：复用浏览器配置文件

```bash
# 首次运行（会提示手动登录）
python -m src --query "test" --user-data-dir "./selenium_profile" --download-dir ./downloads --max-results 1

# 后续运行（自动复用登录状态）
python -m src --query "deep learning" --user-data-dir "./selenium_profile" --download-dir ./downloads
```

## CLI 参数

```bash
python -m src --help
```

| 参数 | 说明 |
|------|------|
| `--query` | 搜索关键词 |
| `--search-url` | IEEE 搜索结果页 URL（保留筛选条件） |
| `--year-from`, `--year-to` | 年份范围（仅 `--query` 模式） |
| `--max-results` | 最大下载数量（默认 25） |
| `--download-dir` | 下载目录 |
| `--browser` | 浏览器类型：`edge`（默认）或 `chrome` |
| `--debugger-address` | 连接已运行的浏览器（如 `127.0.0.1:9222`） |
| `--user-data-dir` | 浏览器配置文件目录（详见下方说明） |
| `--headless` | 无界面模式 |
| `-v`, `--verbose` | 显示详细进度 |
| `--debug` | 显示调试日志 |
| `--sleep-between` | 下载间隔秒数（默认 5） |
| `--per-download-timeout` | 单个下载超时秒数（默认 300） |
| `--stats` | 显示下载统计信息 |
| `--list [status]` | 列出论文（all/downloaded/skipped/failed/pending） |
| `--search-db KEYWORD` | 在数据库中搜索论文 |
| `--export [json/csv]` | 导出论文列表 |
| `--retry-failed` | 重试下载失败的论文 |
| `--migrate-jsonl` | 从旧版 JSONL 迁移到数据库 |
| `--tasks` | 显示最近的下载任务 |

### 关于 `--user-data-dir`

浏览器配置文件目录包含登录状态、cookies、扩展等。有两种使用方式：

**方式 A：创建新的配置目录（推荐用于调试模式）**

```bash
# 创建一个新的空目录，浏览器会在其中创建新的配置文件
--user-data-dir="./selenium_profile"
```

**方式 B：复用现有浏览器配置（包含已登录的会话）**

浏览器默认配置目录位置：

| 浏览器 | 操作系统 | 默认路径 |
|--------|----------|----------|
| Chrome | Windows | `C:\Users\<用户名>\AppData\Local\Google\Chrome\User Data` |
| Chrome | macOS | `~/Library/Application Support/Google/Chrome` |
| Chrome | Linux | `~/.config/google-chrome` |
| Edge | Windows | `C:\Users\<用户名>\AppData\Local\Microsoft\Edge\User Data` |
| Edge | macOS | `~/Library/Application Support/Microsoft Edge` |
| Edge | Linux | `~/.config/microsoft-edge` |

> ⚠️ **注意**：直接使用默认配置目录可能与正在运行的浏览器冲突。建议复制一份或使用调试模式连接已运行的浏览器。

**复用已有配置示例：**

```bash
# Windows - 复用 Chrome 默认配置（确保 Chrome 已关闭）
python -m src --query "test" --user-data-dir "C:\Users\你的用户名\AppData\Local\Google\Chrome\User Data" --download-dir ./downloads

# Linux - 复用 Chrome 配置
python -m src --query "test" --user-data-dir ~/.config/google-chrome --download-dir ./downloads
```

## 输出文件

下载目录中包含：

- `*.pdf`：下载的论文 PDF
- `papers.db`：SQLite 数据库（论文记录和下载任务）
- `download_state.jsonl`：旧版状态记录（兼容）

## 数据库功能

工具使用 SQLite 数据库管理下载记录，支持以下功能：

### 查看统计信息

```bash
python -m src --download-dir ./downloads --stats
```

输出示例：
```
=== Download Statistics ===
  Total papers:    150
  Downloaded:      120
  Skipped:         25
  Failed:          5
  Pending:         0
  Total size:      450.5 MB
```

### 列出论文

```bash
# 列出所有已下载的论文
python -m src --download-dir ./downloads --list downloaded

# 列出失败的论文
python -m src --download-dir ./downloads --list failed
```

### 搜索论文

```bash
python -m src --download-dir ./downloads --search-db "reinforcement learning"
```

### 重试失败的论文

```bash
python -m src --download-dir ./downloads --retry-failed --debugger-address "127.0.0.1:9222" --browser chrome
```

### 导出论文列表

```bash
# 导出为 JSON
python -m src --download-dir ./downloads --export json

# 导出为 CSV
python -m src --download-dir ./downloads --export csv
```

### 查看下载任务历史

```bash
python -m src --download-dir ./downloads --tasks
```

### 从旧版迁移

如果之前使用过 JSONL 格式：

```bash
python -m src --download-dir ./downloads --migrate-jsonl
```

## 特性说明

### 智能跳过无权限论文

工具会自动检测以下情况并跳过：
- 页面显示 "access denied"、"purchase pdf" 等提示
- 需要额外购买或订阅的论文

跳过的论文会记录在 `download_state.jsonl` 中，状态为 `skipped`。

### 下载重试机制

- 网络错误、超时等情况会自动重试（最多 3 次）
- 无权限错误不会重试，直接跳过

### 多种下载策略

1. 先尝试直接 PDF URL（最快）
2. 失败则加载 stamp 页面，检测 iframe/embed
3. 尝试点击下载按钮

## 常见问题

### 端口连接失败

确保：
1. 已关闭所有 Chrome 进程再启动调试模式
2. 使用 `--user-data-dir` 指定独立目录
3. 检查端口是否开放：

```bash
# Linux/macOS
nc -zv 127.0.0.1 9222

# Windows PowerShell
Test-NetConnection -ComputerName 127.0.0.1 -Port 9222
```

### PDF 在浏览器内显示而不是下载

在 Chrome 设置中禁用内置 PDF 查看器：
1. 打开 `chrome://settings/content/pdfDocuments`
2. 选择 **"下载 PDF 文件，而不是在 Chrome 中自动打开它们"**

### 下载超时

- 增加 `--per-download-timeout` 值
- 减小 `--max-results` 分批下载
- 检查网络连接

### 找不到论文

- 确认搜索条件正确
- 使用 `-v` 查看详细日志
- 使用 `--debug` 查看调试信息

### ChromeDriver 版本不匹配

```bash
# 检查 Chrome 版本
google-chrome --version

# 下载对应版本的 ChromeDriver
# https://googlechromelabs.github.io/chrome-for-testing/
```

## 项目结构

```
src/
├── __init__.py
├── __main__.py
├── cli.py              # CLI 入口
├── ieee_xplore.py      # IEEE Xplore 自动化逻辑
├── selenium_utils.py   # WebDriver 工具函数
└── state.py            # 状态管理
```

## 法律声明

使用本工具时请遵守：

- IEEE Xplore 使用条款
- 您所在机构的许可协议
- 相关法律法规

本工具仅供拥有合法访问权限的用户使用。
