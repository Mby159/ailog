# AILog

> AI 交互产物的个人数据主权开放协议

**平台无关的 AI 对话格式标准** — 把分散在 ChatGPT、Claude、Gemini 等平台的对话记录，统一成一种开放格式，让你真正拥有自己的 AI 交互数据。

> [English](README_en.md) | 中文

## 为什么需要 AILog？

你的 AI 对话散落在各个平台：ChatGPT、Claude、Gemini、DeepSeek……每个平台都是数据孤岛，导出格式各不相同，无法统一搜索、分析和迁移。

AILog 定义了一种开放格式（`.ailog`），让所有 AI 对话可以被：

- 🔍 **统一搜索** — 用 File Brain 语义搜索所有对话
- 🔒 **隐私标注** — GhostGuard 自动检测敏感信息
- 📦 **自由迁移** — 导入导出不受平台锁定
- 📝 **知识沉淀** — 导出为 Obsidian Markdown 做知识管理

## 快速开始

### 安装

```bash
# 克隆项目
git clone https://github.com/Mby159/ailog.git
cd ailog

# 安装为本地可编辑包
python -m pip install -e .

# 查看命令
ailog --help

# 开发者也可以使用模块方式
python -m ailog.cli --help
```

### 导入 ChatGPT 对话

```bash
# 从 conversations.json 导入
ailog import conversations.json -o my-chats.ailog

# 从 ChatGPT 导出的 zip 文件导入
ailog import chatgpt-export.zip -o my-chats.ailog

# 自动检测格式
ailog import data.json --format auto -o output.ailog
```

### 导入 Claude 对话

```bash
ailog import claude-conversations.json -o claude-chats.ailog
```

### 查看文件信息

```bash
ailog info my-chats.ailog -v
```

输出示例：
```
AILog Version: 0.1
Platform: chatgpt
Interactions: 42
Sessions: 7

Sessions:
  Python Quick Sort (5 turns)
  API Key Question (3 turns)
  ...
```

### 隐私扫描

```bash
# 扫描敏感信息
ailog scan my-chats.ailog

# 自动脱敏
ailog scan my-chats.ailog --auto-redact -o redacted.ailog
```

### 增量同步

```bash
# 首次同步：全量导入
ailog sync conversations.json -p chatgpt -o synced.ailog

# 再次同步：只导入新增消息（已导入的自动跳过）
ailog sync conversations.json -p chatgpt -o synced.ailog
```

### 格式转换

```bash
# 导出为 Obsidian Markdown
ailog export my-chats.ailog --format obsidian -o ./obsidian-vault/

# 导出为 HTML（Claude 风格，支持深色模式）
ailog export my-chats.ailog --format html -o my-chats.html

# 导出为 PDF
ailog export my-chats.ailog --format pdf -o my-chats.pdf

# JSONL → JSON
ailog convert my-chats.ailog --to json -o my-chats.json
```

## .ailog 格式

`.ailog` 使用 JSONL 格式（每行一个 JSON 对象）：

- **第 1 行**：元数据（来源平台、导出时间、导出器）
- **第 2 行起**：交互记录（每个 user+assistant 轮次一行）

### 核心字段（7个必填）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 交互唯一 ID |
| `timestamp` | ISO 8601 | 发生时间 |
| `session_id` | string | 会话 ID |
| `turn_index` | integer | 轮次序号 |
| `messages` | Message[] | 消息列表 |
| `messages[].role` | string | user/assistant/system/tool |
| `messages[].content` | string | 消息内容 |

### 完整规范

见 [`spec/FORMAT.md`](spec/FORMAT.md)

### 示例

```jsonl
{"ailog_version":"0.1","type":"metadata","metadata":{"source_platform":"chatgpt","export_timestamp":"2026-04-26T08:00:00Z","exporter":"ailog-importer-chatgpt/0.1.0"}}
{"ailog_version":"0.1","type":"interaction","id":"ix_01JABC123","timestamp":"2026-04-26T08:00:00Z","session_id":"sess_01JXYZ456","turn_index":1,"messages":[{"role":"user","content":"帮我写一个 Python 快速排序"},{"role":"assistant","content":"```python\ndef quicksort(arr): ...\n```","model":"gpt-4o","model_provider":"openai"}],"artifacts":[{"id":"art_001","type":"code","name":"quicksort.py","language":"python"}],"sensitivity":{"max_risk_level":"low","detected_items":[]}}
```

## 支持的平台

| 平台 | 状态 | 导入 | 导出 |
|------|------|------|------|
| ChatGPT | ✅ 已支持 | conversations.json / zip | — |
| Claude | ✅ 已支持 | JSON 对话格式 | — |
| DeepSeek | ✅ 已支持 | JSON 对话格式 + R1 思维链 | — |
| Gemini | ✅ 已支持 | JSON 对话格式（model 角色） | — |
| YouTube | ✅ 已支持 | JSON 字幕 / SRT / VTT | — |
| Bilibili | ✅ 已支持 | JSON 字幕（content/from/to） | — |
| Generic JSON | ✅ 已支持 | messages 数组格式 | — |
| Notion | 🔜 计划中 | — | .ailog → Notion |
| Obsidian | ✅ 已支持 | — | .ailog → Markdown |
| HTML | ✅ 已支持 | — | .ailog → Claude风格HTML |
| PDF | ✅ 已支持 | — | .ailog → 可打印PDF |

## 架构

```
.ailog 开放格式
    │
    ├── importers/         ← 各平台 → .ailog
    │   ├── chatgpt.py      ← ChatGPT (mapping 树遍历)
    │   ├── claude.py       ← Claude (human/assistant)
    │   ├── deepseek.py     ← DeepSeek (R1 思维链)
    │   ├── gemini.py       ← Gemini (model 角色)
    │   ├── youtube.py      ← YouTube 字幕 (JSON/SRT/VTT)
    │   ├── bilibili.py     ← Bilibili 字幕 (content/from/to)
    │   └── generic_json.py ← 通用 JSON 兜底
    │
    ├── exporters/         ← .ailog → 各平台
    │   ├── obsidian.py     ← Markdown + YAML frontmatter
    │   ├── html.py         ← Claude 风格 HTML（深浅主题）
    │   ├── pdf.py          ← 可打印 PDF
    │   └── notion.py       ← Notion 页面（async）
    │
    ├── bridge/            ← 与现有工具集成
    │   ├── ghostguard.py   ← 隐私扫描
    │   └── filebrain.py    ← 语义搜索 + Markdown 导出
    │
    ├── sync.py            ← 增量同步（差量导入）
    │
    ├── core/              ← 数据模型
    │   └── models.py
    │
    ├── cli.py             ← 命令行工具 (5个子命令)
    └── mcp_server.py       ← MCP 服务器 (4个工具)
```

## 设计原则

1. **格式极简** — 7个必填字段，5分钟写完 parser
2. **隐私标注不加密** — 格式层标注敏感级别，GhostGuard 做脱敏
3. **Artifact 一等公民** — AI 生成的代码/图片不是附庸
4. **JSONL 优先** — 流式可追加，大文件友好
5. **custom 自由扩展** — 平台特有字段不挤进核心

## 与现有项目的关系

| 项目 | 角色 |
|------|------|
| [GhostGuard](https://github.com/Mby159/ghostguard) | 隐私扫描引擎 |
| [privacy-guard](https://github.com/Mby159/privacy-guard) | 精简隐私引擎 |
| [privacy-proxy](https://github.com/Mby159/privacy-proxy) | OpenAI 兼容隐私代理 |
| [SplitMind](https://github.com/Mby159/splitmind) | 多 AI 任务编排 |
| [File Brain](https://github.com/Mby159/file-brain) | 本地文件语义搜索 |

## 运行测试

```bash
python -m pytest tests/ -v
```

## 许可证

MIT

---

> **数字认知主权三定律**：
> 1. 可读律 — 用户有权阅读自己的全部 AI 交互记录
> 2. 可迁律 — 用户有权将记录迁移到任意平台
> 3. 可控律 — 用户有权控制哪些数据可以被谁访问
