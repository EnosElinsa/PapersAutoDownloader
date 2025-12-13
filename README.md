# PapersAutoDownloader (IEEE Xplore)

基于 Selenium 的 IEEE Xplore 论文自动下载工具。

适用于拥有 **授权访问** （个人订阅、机构访问等）的用户，通过模拟真实浏览器行为批量下载论文。

## 功能特性

### 核心功能
- **双模式支持**：命令行 (CLI) 和图形界面 (GUI)
- **Material Design 3 GUI**：基于 Flet/Flutter 的现代化界面
- 支持 Edge / Chrome 浏览器（Linux/macOS 推荐 Chrome）
- 多种登录方式：手动登录、凭证登录、复用已登录的浏览器
- **连接已运行的浏览器**（推荐）：复用已登录的 Chrome/Edge 会话
- 支持关键词搜索或直接使用 IEEE 搜索结果 URL
- 自动分页下载，支持断点续传
- **SQLite 数据库管理**：论文记录、任务历史、统计信息
- **智能跳过无权限论文**：自动检测并跳过无访问权限的论文
- 下载失败自动重试（可配置重试次数和间隔）

### GUI 特色功能
- **深色/浅色主题切换**：支持深色模式，保护眼睛
- **下载完成系统通知**：Windows/macOS/Linux 原生通知
- **论文详情查看**：显示标题、作者、摘要、文件信息
- **单篇论文重试下载**：针对失败的论文单独重试
- **搜索历史**：保存最近 20 条搜索记录，快速重复搜索
- **批量操作**：重试所有失败、删除指定状态、导出可见论文
- **任务管理**：查看任务详情、编辑任务状态、重置失败/跳过的论文
- **日志导出**：导出下载日志用于调试
- **即时停止**：点击停止按钮可立即中断下载（无需等待超时）
- **PDF 缓存**：缓存文件列表避免重复扫描

## 安装

```bash
pip install -r requirements.txt
```

## 启动方式

### GUI 模式（推荐）

```bash
python -m src --gui
```

![GUI Screenshot](docs/gui-screenshot.png)

### CLI 模式

```bash
python -m src --query "deep learning" --debugger-address "127.0.0.1:9222" --browser chrome
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

## GUI 使用说明

### 主界面

- **Download**：下载页面，配置搜索条件和浏览器设置
- **Papers**：论文库，管理已下载的论文
- **Tasks**：任务历史，查看和管理下载任务
- **Settings**：设置页面，配置主题、重试策略等

### 下载流程

1. 选择搜索方式（关键词或 URL）
2. 配置浏览器设置（推荐使用"连接已运行的浏览器"）
3. 点击 "Launch Browser" 启动调试模式浏览器（或手动启动）
4. 在浏览器中登录 IEEE Xplore
5. 点击 "Start Download" 开始下载
6. 可随时点击 "Stop Download" 立即停止

### 论文管理

- 点击论文卡片查看详情（标题、作者、摘要、文件信息）
- 使用筛选器按状态过滤论文
- 批量操作：重试失败、删除、导出

### 任务管理

- 查看任务详情和统计信息
- 编辑任务状态
- 重置失败/跳过的论文为待下载状态

## CLI 参数

```bash
python -m src --help
```

| 参数 | 说明 |
|------|------|
| `--gui` | 启动图形界面 |
| `--query` | 搜索关键词 |
| `--search-url` | IEEE 搜索结果页 URL（保留筛选条件） |
| `--year-from`, `--year-to` | 年份范围（仅 `--query` 模式） |
| `--max-results` | 最大下载数量（默认 25） |
| `--download-dir` | 下载目录 |
| `--browser` | 浏览器类型：`edge`（默认）或 `chrome` |
| `--debugger-address` | 连接已运行的浏览器（如 `127.0.0.1:9222`） |
| `--user-data-dir` | 浏览器配置文件目录 |
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

## 输出文件

下载目录中包含：

- `*.pdf`：下载的论文 PDF（以论文标题命名）
- `papers.db`：SQLite 数据库（论文记录和下载任务）
- `download_state.jsonl`：旧版状态记录（兼容）

## 数据库功能

### 查看统计信息

```bash
python -m src --download-dir ./downloads --stats
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

- 增加 `--per-download-timeout` 值（GUI 中在 Settings 页面配置）
- 减小 `--max-results` 分批下载
- 检查网络连接

### 停止按钮无响应

已修复：现在点击停止按钮会立即中断下载，无需等待超时。

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
├── __main__.py          # 入口点（支持 --gui 和 CLI）
├── cli.py               # CLI 命令行接口
├── database.py          # SQLite 数据库管理
├── ieee_xplore.py       # IEEE Xplore 自动化逻辑
├── selenium_utils.py    # WebDriver 工具函数
├── state.py             # 状态管理（旧版兼容）
└── gui/                 # GUI 模块（Flet/Material Design 3）
    ├── __init__.py      # 包导出
    ├── app.py           # 主应用类
    ├── theme.py         # 主题管理（深色/浅色模式）
    ├── components/      # 可复用 UI 组件
    │   └── widgets.py   # 统计卡片、标题栏等
    ├── utils/           # 工具函数
    │   └── helpers.py   # URL 处理、通知、文件操作
    ├── views/           # 页面视图
    │   ├── download_view.py   # 下载页面
    │   ├── papers_view.py     # 论文库页面
    │   ├── tasks_view.py      # 任务历史页面
    │   └── settings_view.py   # 设置页面
    └── dialogs/         # 对话框
        ├── paper_dialogs.py   # 论文详情/编辑对话框
        └── task_dialogs.py    # 任务详情/编辑对话框
```

## 法律声明

使用本工具时请遵守：

- IEEE Xplore 使用条款
- 您所在机构的许可协议
- 相关法律法规

本工具仅供拥有合法访问权限的用户使用。
