# AILog Format Specification v0.1

> **Status**: Draft
> **Author**: AILog Protocol Working Group
> **Date**: 2026-04-26
> **License**: CC0-1.0 (Public Domain)

---

## 第一性原理设计推导

### Step 1 — 回归根本假设

AI 交互产物的最基础公理：

1. **交互必有双方** — 用户（human）和 AI（agent），每轮对话至少包含一个用户输入和一个 AI 回复
2. **交互有时序** — 先说后答，天然有序，时间戳不可少
3. **交互有上下文** — 前后轮次之间有逻辑关联，不能孤立理解
4. **交互有身份** — 不同的 AI 平台、模型、版本产生的交互，质量差异极大
5. **交互可能含敏感** — 用户在对话中无意泄露隐私是常态，不是例外
6. **交互可能含产物** — AI 生成的不只是文本，还有代码、图片、文件等
7. **交互属于用户** — 用户有权导出、迁移、删除自己的全部交互记录

### Step 2 — 费曼澄清

.ailog 就像一张**银行流水单**：

- 每笔交易有时间、金额、对方（谁说了什么）
- 不同银行（AI 平台）的流水格式不同，但都能转成统一格式
- 你可以选哪些交易导出（隐私控制）
- 任何记账软件（索引工具）都能读取统一格式

### Step 3 — 剥离噪音与迷思

**迷思 1**：「格式应该尽量丰富，覆盖所有平台的特殊字段」
→ **错**。格式越丰富，实现门槛越高，没人愿意适配。正确做法：**核心字段极简，扩展字段可选**。

**迷思 2**：「应该用二进制格式提升效率」
→ **错**。用户第一需求是"可读可理解"，不是"高效存储"。JSON/YAML 优先，人类可读是刚需。

**迷思 3**：「隐私保护应该在格式层加密」
→ **错**。格式层只做标注（标记哪些字段含敏感信息），加密/脱敏是工具层的职责。格式和工具解耦。

### Step 4 — 推理新方案

基于上述挑战，.ailog 的核心设计原则：

1. **JSON Lines（.jsonl）为主格式** — 每行一个 interaction，流式可追加，不像完整 JSON 那样需要重新序列化整个文件
2. **核心字段 7 个，扩展字段自由添加** — 实现者只需支持核心字段即可
3. **隐私标注而非隐私加密** — 用 `sensitivity` 字段标记敏感级别，脱敏/加密交给 GhostGuard 等工具
4. **原生支持 artifacts** — AI 生成的代码、图片、文件等，不是附件，是一等公民

### Step 5 — 最终极简路径

一个 .ailog 文件 = 一组有序的 interaction（交互），每个 interaction = 谁在什么时候说了什么 + 元数据。

完。

---

## 格式定义

### 文件扩展名

- `.ailog` — 推荐（JSONL 格式）
- `.ailog.json` — 替代（完整 JSON 格式，适合小文件）

### MIME Type

`application/x-ailog+jsonl`

### 编码

UTF-8，无 BOM，LF 换行

---

## 核心数据结构

### AILogFile（完整文件 — .ailog.json 模式）

```json
{
  "ailog_version": "0.1",
  "metadata": { ... },
  "interactions": [ ... ]
}
```

### AILogFileMetadata

```json
{
  "source_platform": "chatgpt",
  "source_url": "https://chat.openai.com",
  "export_timestamp": "2026-04-26T08:00:00Z",
  "exporter": "ailog-importer-chatgpt/0.1.0",
  "owner": {
    "id": "user@example.com",
    "id_type": "email",
    "display_name": "张三"
  },
  "tags": ["work", "coding"],
  "custom": {}
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| source_platform | string | ✅ | 来源平台 ID（见平台注册表） |
| source_url | string | ❌ | 来源平台 URL |
| export_timestamp | string (ISO 8601) | ✅ | 导出时间 |
| exporter | string | ✅ | 导出器标识（name/version） |
| owner | object | ❌ | 数据所有者信息 |
| owner.id | string | ❌ | 所有者标识 |
| owner.id_type | string | ❌ | 标识类型：email / username / anonymous |
| owner.display_name | string | ❌ | 显示名称 |
| tags | string[] | ❌ | 全局标签 |
| custom | object | ❌ | 平台/工具自定义扩展字段 |

### Interaction（交互 — 核心单元）

JSONL 模式下每行一个 Interaction：

```json
{
  "id": "ix_01JABC123",
  "timestamp": "2026-04-26T08:00:00Z",
  "session_id": "sess_01JXYZ456",
  "turn_index": 3,
  "messages": [ ... ],
  "artifacts": [ ... ],
  "sensitivity": { ... },
  "custom": {}
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | string | ✅ | 交互唯一 ID（建议 ULID/UUIDv7） |
| timestamp | string (ISO 8601) | ✅ | 交互发生时间 |
| session_id | string | ✅ | 会话 ID（同一对话的所有交互共享） |
| turn_index | integer | ✅ | 在会话中的轮次序号（从 1 开始） |
| messages | Message[] | ✅ | 消息列表（至少 1 条） |
| artifacts | Artifact[] | ❌ | AI 生成的产物 |
| sensitivity | SensitivityInfo | ❌ | 隐私敏感度标注 |
| custom | object | ❌ | 扩展字段 |

### Message（消息）

```json
{
  "role": "user",
  "content": "帮我写一个 Python 快速排序",
  "content_type": "text",
  "timestamp": "2026-04-26T08:00:00Z",
  "model": "gpt-4o",
  "model_provider": "openai",
  "token_usage": {
    "prompt_tokens": 12,
    "completion_tokens": 156,
    "total_tokens": 168
  },
  "custom": {}
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| role | string | ✅ | "user" / "assistant" / "system" / "tool" |
| content | string | ✅ | 消息文本内容 |
| content_type | string | ❌ | "text"（默认）/ "markdown" / "html" / "code" / "image" / "audio" / "file" |
| timestamp | string (ISO 8601) | ❌ | 消息级时间戳（比 interaction 级更精确） |
| model | string | ❌ | 使用的模型名 |
| model_provider | string | ❌ | 模型提供商 |
| token_usage | TokenUsage | ❌ | Token 用量 |
| custom | object | ❌ | 扩展字段 |

### TokenUsage

```json
{
  "prompt_tokens": 12,
  "completion_tokens": 156,
  "total_tokens": 168
}
```

### Artifact（产物 — 一等公民）

```json
{
  "id": "art_01JDEF789",
  "type": "code",
  "name": "quicksort.py",
  "content": "def quicksort(arr): ...",
  "language": "python",
  "size_bytes": 432,
  "hash": "sha256:abc123...",
  "source_message_index": 1,
  "custom": {}
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | string | ✅ | 产物唯一 ID |
| type | string | ✅ | "code" / "image" / "document" / "data" / "audio" / "video" / "other" |
| name | string | ✅ | 文件名或标题 |
| content | string | ❌ | 内联内容（文本类产物） |
| url | string | ❌ | 外部链接（图片/文件等） |
| language | string | ❌ | 编程语言（type=code 时） |
| size_bytes | integer | ❌ | 文件大小 |
| hash | string | ❌ | 内容哈希（算法:值 格式） |
| source_message_index | integer | ❌ | 产生此产物的 message 在 messages 中的索引 |
| custom | object | ❌ | 扩展字段 |

### SensitivityInfo（隐私敏感度标注）

> 设计来源：GhostGuard DetectionResult + privacy-proxy SensitiveItem

```json
{
  "max_risk_level": "high",
  "detected_items": [
    {
      "info_type": "phone",
      "risk_level": "high",
      "field": "messages[0].content",
      "redacted": false,
      "strategy": "mask"
    },
    {
      "info_type": "api_key",
      "risk_level": "critical",
      "field": "messages[1].content",
      "redacted": true,
      "strategy": "placeholder"
    }
  ],
  "scanned_by": "ghostguard/0.1.0",
  "scan_timestamp": "2026-04-26T08:00:01Z"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| max_risk_level | string | ✅ | "low" / "medium" / "high" / "critical" |
| detected_items | SensitivityItem[] | ❌ | 检测到的敏感信息列表 |
| scanned_by | string | ❌ | 扫描工具标识 |
| scan_timestamp | string (ISO 8601) | ❌ | 扫描时间 |

### SensitivityItem

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| info_type | string | ✅ | 类型：phone / email / id_card / bank_card / ssn / api_key / password / token / ipv4 / url / amount / custom |
| risk_level | string | ✅ | "low" / "medium" / "high" / "critical" |
| field | string | ✅ | 敏感信息所在字段路径（JSONPath 风格） |
| redacted | boolean | ✅ | 是否已脱敏 |
| strategy | string | ❌ | 脱敏策略：placeholder / mask / remove / hash |

---

## 平台注册表

已知 AI 平台的标准化 ID：

| platform_id | 名称 | 原生导出格式 |
|-------------|------|-------------|
| chatgpt | ChatGPT (OpenAI) | conversations.json |
| claude | Claude (Anthropic) | 无官方导出 |
| gemini | Gemini (Google) | 无官方导出 |
| deepseek | DeepSeek | 无官方导出 |
| grok | Grok (xAI) | 无官方导出 |
| kimi | Kimi (月之暗面) | 无官方导出 |
| doubao | 豆包 (字节跳动) | 无官方导出 |
| tongyi | 通义千问 (阿里) | 无官方导出 |
| wenxin | 文心一言 (百度) | 无官方导出 |
| youtube | YouTube | — |
| bilibili | Bilibili | — |
| notion | Notion | — |
| obsidian | Obsidian | — |
| local_model | 本地模型 | — |
| custom | 自定义 | — |

---

## JSONL 模式示例

文件：`my-chatgpt-conversations.ailog`

```jsonl
{"ailog_version":"0.1","type":"metadata","metadata":{"source_platform":"chatgpt","source_url":"https://chat.openai.com","export_timestamp":"2026-04-26T08:00:00Z","exporter":"ailog-importer-chatgpt/0.1.0","owner":{"id_type":"anonymous"},"tags":["coding"]}}
{"ailog_version":"0.1","type":"interaction","id":"ix_01JABC123","timestamp":"2026-04-26T08:00:00Z","session_id":"sess_01JXYZ456","turn_index":1,"messages":[{"role":"user","content":"帮我写一个 Python 快速排序","content_type":"text"},{"role":"assistant","content":"```python\ndef quicksort(arr):\n    if len(arr) <= 1:\n        return arr\n    pivot = arr[len(arr) // 2]\n    left = [x for x in arr if x < pivot]\n    middle = [x for x in arr if x == pivot]\n    right = [x for x in arr if x > pivot]\n    return quicksort(left) + middle + quicksort(right)\n```","content_type":"markdown","model":"gpt-4o","model_provider":"openai","token_usage":{"prompt_tokens":12,"completion_tokens":156,"total_tokens":168}}],"artifacts":[{"id":"art_001","type":"code","name":"quicksort.py","language":"python","source_message_index":1}],"sensitivity":{"max_risk_level":"low","detected_items":[],"scanned_by":"ghostguard/0.1.0"}}
{"ailog_version":"0.1","type":"interaction","id":"ix_01JABC124","timestamp":"2026-04-26T08:01:00Z","session_id":"sess_01JXYZ456","turn_index":2,"messages":[{"role":"user","content":"我的手机号是13812345678，请帮我注册账号"},{"role":"assistant","content":"好的，我会帮您使用手机号 138****5678 注册账号","content_type":"text","model":"gpt-4o","model_provider":"openai"}],"sensitivity":{"max_risk_level":"high","detected_items":[{"info_type":"phone","risk_level":"high","field":"messages[0].content","redacted":true,"strategy":"mask"}],"scanned_by":"ghostguard/0.1.0"}}
```

---

## 完整 JSON 模式示例

文件：`my-chatgpt-conversations.ailog.json`

```json
{
  "ailog_version": "0.1",
  "metadata": {
    "source_platform": "chatgpt",
    "source_timestamp": "2026-04-26T08:00:00Z",
    "export_timestamp": "2026-04-26T16:00:00Z",
    "exporter": "ailog-importer-chatgpt/0.1.0",
    "owner": {
      "id_type": "anonymous"
    },
    "tags": ["coding"]
  },
  "interactions": [
    {
      "id": "ix_01JABC123",
      "timestamp": "2026-04-26T08:00:00Z",
      "session_id": "sess_01JXYZ456",
      "turn_index": 1,
      "messages": [
        {
          "role": "user",
          "content": "帮我写一个 Python 快速排序",
          "content_type": "text"
        },
        {
          "role": "assistant",
          "content": "```python\ndef quicksort(arr):\n    if len(arr) <= 1:\n        return arr\n    pivot = arr[len(arr) // 2]\n    left = [x for x in arr if x < pivot]\n    middle = [x for x in arr if x == pivot]\n    right = [x for x in arr if x > pivot]\n    return quicksort(left) + middle + quicksort(right)\n```",
          "content_type": "markdown",
          "model": "gpt-4o",
          "model_provider": "openai",
          "token_usage": {
            "prompt_tokens": 12,
            "completion_tokens": 156,
            "total_tokens": 168
          }
        }
      ],
      "artifacts": [
        {
          "id": "art_001",
          "type": "code",
          "name": "quicksort.py",
          "language": "python",
          "source_message_index": 1
        }
      ],
      "sensitivity": {
        "max_risk_level": "low",
        "detected_items": [],
        "scanned_by": "ghostguard/0.1.0"
      }
    }
  ]
}
```

---

## 与现有项目的关系

### GhostGuard / privacy-guard → SensitivityInfo 层

.ailog 的 `SensitivityInfo` 和 `SensitivityItem` 直接复用 GhostGuard 的数据模型：

| GhostGuard 类型 | .ailog 对应 |
|----------------|-------------|
| SensitivityLevel | sensitivity.max_risk_level |
| DetectionResult | SensitivityItem |
| RedactionStrategy | SensitivityItem.strategy |
| DetectionResult.info_type | SensitivityItem.info_type |

**集成方式**：Importer 在导出时调用 GhostGuard 扫描，结果写入 sensitivity 字段。

### privacy-proxy → 实时脱敏

privacy-proxy 可以作为 .ailog 导入/导出的中间层：
- 导入时：proxy 自动脱敏（如果用户选择）
- 导出时：proxy 自动还原（如果用户持有 mapping）

### SplitMind → 多源编排

SplitMind 的任务拆分能力可用于：
- 将一个复杂对话拆分为多个 .ailog 交互（按话题分割）
- 多 AI 协作时，每个 AI 的输出分别生成 interaction，最终汇总

### File Brain MCP → 索引与检索

File Brain 的 SimpleSearchEngine 可以直接索引 .ailog 文件：
- 每个 interaction 的 `messages[].content` 作为搜索目标
- `session_id` / `timestamp` / `tags` 作为过滤条件
- `artifacts` 的内容独立索引
- 向量搜索支持语义检索对话

---

## Importer 架构

```
ailog/
├── spec/
│   ├── FORMAT.md          ← 本文档
│   └── PLATFORMS.md       ← 平台注册表
├── importers/
│   ├── base.py            ← BaseImporter 抽象类
│   ├── chatgpt.py         ← ChatGPT → .ailog
│   ├── claude.py          ← Claude → .ailog
│   ├── gemini.py          ← Gemini → .ailog
│   ├── deepseek.py        ← DeepSeek → .ailog
│   ├── youtube.py         ← YouTube 字幕 → .ailog
│   ├── bilibili.py        ← B站字幕 → .ailog
│   ├── notion.py          ← Notion 页面 → .ailog
│   └── generic_json.py    ← 通用 JSON → .ailog
├── exporters/
│   ├── base.py            ← BaseExporter 抽象类
│   ├── obsidian.py        ← .ailog → Obsidian Markdown
│   ├── notion.py          ← .ailog → Notion 页面
│   └── pdf.py             ← .ailog → PDF
├── bridge/
│   ├── ghostguard.py      ← GhostGuard 集成（隐私扫描）
│   ├── filebrain.py       ← File Brain MCP 集成（索引/搜索）
│   ├── splitmind.py       ← SplitMind 集成（任务编排）
│   └── privacy_proxy.py   ← privacy-proxy 集成（实时脱敏）
├── core/
│   ├── models.py          ← 数据模型（Interaction, Message, Artifact...）
│   ├── reader.py          ← .ailog 文件读取器（JSONL/JSON）
│   ├── writer.py          ← .ailog 文件写入器
│   └── validator.py       ← 格式校验器
├── cli.py                 ← 命令行工具
└── mcp_server.py          ← MCP 服务器
```

### BaseImporter 接口

```python
from abc import ABC, abstractmethod
from typing import List, Optional
from core.models import AILogFile, Interaction

class BaseImporter(ABC):
    """Base class for AILog importers."""

    platform_id: str  # e.g. "chatgpt"

    @abstractmethod
    def detect(self, source_path: str) -> bool:
        """Detect if source is from this platform."""
        ...

    @abstractmethod
    def parse(self, source_path: str) -> AILogFile:
        """Parse source into AILogFile."""
        ...

    def scan_sensitivity(self, ailog: AILogFile) -> AILogFile:
        """Scan and annotate sensitivity using GhostGuard."""
        # Default: use GhostGuard if available
        try:
            from ghostguard import GhostGuard
            guard = GhostGuard()
            for interaction in ailog.interactions:
                for msg in interaction.messages:
                    result = guard.process_input(msg.content)
                    if result.has_sensitive_info:
                        # annotate sensitivity field
                        ...
            return ailog
        except ImportError:
            return ailog
```

---

## 设计决策记录

| # | 决策 | 理由 | 替代方案 |
|---|------|------|---------|
| D1 | JSONL 为主格式 | 流式可追加，大文件友好，每行独立可解析 | 完整 JSON（内存开销大）、SQLite（不可读）、Protobuf（不可读） |
| D2 | 核心字段极简 | 降低实现门槛，7个必填字段5分钟能写完 parser | 字段丰富（实现者望而却步） |
| D3 | 隐私标注不加密 | 格式层和工具层解耦，GhostGuard 等工具做脱敏 | 格式层加密（过度设计，破坏可读性） |
| D4 | Artifact 一等公民 | AI 生成的代码/图片不是附庸，需要独立索引 | 只存文本（丢失非文本产物） |
| D5 | custom 自由扩展 | 各平台特有字段（Claude artifacts、Gemini grounding）不必挤进核心 | 全部注册（标准膨胀） |
| D6 | SensitivityInfo 嵌入 | 导出时标注敏感信息，导入时按需脱敏 | 不标注（隐私控制无据可依） |
| D7 | ULID/UUIDv7 做 ID | 时间有序 + 全局唯一，比 UUIDv4 更适合按时间排序 | 自增整数（跨文件冲突）、UUIDv4（无序） |

---

## 版本演进计划

| 版本 | 目标 | 新增 |
|------|------|------|
| v0.1 | **当前** | 核心格式定义 + JSONL/JSON 双模式 |
| v0.2 | Importer MVP | ChatGPT Importer + GhostGuard 桥接 + CLI |
| v0.3 | 多平台 | Claude/Gemini/DeepSeek Importer |
| v0.4 | 索引集成 | File Brain MCP 桥接 + 语义搜索 |
| v0.5 | 导出器 | Obsidian/Notion/PDF 导出器 |
| v1.0 | 正式版 | 完整测试 + 文档 + 示例 + MCP 服务器 |

---

## 附录 A：与竞品格式对比

| 特性 | .ailog | ChatGPT 导出 JSON | AI Exporter (MD) | AI 记忆链 |
|------|--------|-------------------|------------------|----------|
| 格式类型 | 开放标准 | 平台私有 | 工具私有 | 商业私有 |
| 跨平台 | ✅ 设计目标 | ❌ 仅 ChatGPT | ⚠️ 部分支持 | ⚠️ 联盟内 |
| 隐私标注 | ✅ 内置 | ❌ | ❌ | ⚠️ 加密存储 |
| 非文本产物 | ✅ Artifact | ❌ | ❌ | ❌ |
| 流式追加 | ✅ JSONL | ❌ | ❌ | ❌ |
| 可读性 | ✅ JSON/JSONL | ✅ JSON | ✅ Markdown | ❌ 加密 |
| 标准化路径 | W3C/IETF | — | — | 专利 |
