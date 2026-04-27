# 贡献指南

感谢你对 AILog 项目的兴趣！欢迎贡献代码、文档或反馈问题。

## 开发环境

```bash
# 克隆项目
git clone https://github.com/your-org/ailog.git
cd ailog

# 创建虚拟环境（推荐）
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # macOS/Linux

# 安装开发依赖
pip install -e ".[all]"

# 运行测试
python -m pytest ailog/tests/ -v
```

## 项目结构

```
ailog/
├── core/models.py          # 数据模型
├── importers/              # 导入器
│   ├── chatgpt.py
│   ├── claude.py
│   └── ...
├── exporters/              # 导出器
│   ├── html.py
│   ├── obsidian.py
│   ├── pdf.py
│   └── notion.py
├── bridge/                 # 外部工具桥接
├── cli.py                  # CLI 入口
├── sync.py                 # 增量同步
└── mcp_server.py           # MCP 服务器
```

## 添加新平台导入器

1. 在 `ailog/importers/` 创建 `xxx.py`
2. 继承 `BaseImporter` 类
3. 实现 `detect()` 和 `parse()` 方法
4. 在 `ailog/importers/__init__.py` 注册
5. 添加测试用例

参考示例：`ailog/importers/chatgpt.py`

## 添加新导出器

1. 在 `ailog/exporters/` 创建 `xxx.py`
2. 继承 `BaseExporter` 类
3. 实现 `export()` 方法
4. 在 `ailog/exporters/__init__.py` 注册
5. 在 `cli.py` 的 `cmd_export` 添加支持

参考示例：`ailog/exporters/obsidian.py`

## 代码规范

- 使用 Python 3.10+ 语法
- 使用 type hints
- 保持函数简短（<50 行）
- 所有公共 API 需要类型标注

## 测试

```bash
# 运行所有测试
python -m pytest ailog/tests/ -v

# 运行单个测试
python -m pytest ailog/tests/test_chatgpt_importer.py -v
```

## 问题反馈

- Bug 报告：https://github.com/your-org/ailog/issues
- 功能建议：https://github.com/your-org/ailog/discussions