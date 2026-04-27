# 璐＄尞鎸囧崡

鎰熻阿浣犲 AILog 椤圭洰鐨勫叴瓒ｏ紒娆㈣繋璐＄尞浠ｇ爜銆佹枃妗ｆ垨鍙嶉闂銆?
## 寮€鍙戠幆澧?
```bash
# 鍏嬮殕椤圭洰
git clone https://github.com/Mby159/ailog.git
cd ailog

# 鍒涘缓铏氭嫙鐜锛堟帹鑽愶級
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # macOS/Linux

# 瀹夎寮€鍙戜緷璧?pip install -e ".[all]"

# 杩愯娴嬭瘯
python -m pytest ailog/tests/ -v
```

## 椤圭洰缁撴瀯

```
ailog/
鈹溾攢鈹€ core/models.py          # 鏁版嵁妯″瀷
鈹溾攢鈹€ importers/              # 瀵煎叆鍣?鈹?  鈹溾攢鈹€ chatgpt.py
鈹?  鈹溾攢鈹€ claude.py
鈹?  鈹斺攢鈹€ ...
鈹溾攢鈹€ exporters/              # 瀵煎嚭鍣?鈹?  鈹溾攢鈹€ html.py
鈹?  鈹溾攢鈹€ obsidian.py
鈹?  鈹溾攢鈹€ pdf.py
鈹?  鈹斺攢鈹€ notion.py
鈹溾攢鈹€ bridge/                 # 澶栭儴宸ュ叿妗ユ帴
鈹溾攢鈹€ cli.py                  # CLI 鍏ュ彛
鈹溾攢鈹€ sync.py                 # 澧為噺鍚屾
鈹斺攢鈹€ mcp_server.py           # MCP 鏈嶅姟鍣?```

## 娣诲姞鏂板钩鍙板鍏ュ櫒

1. 鍦?`ailog/importers/` 鍒涘缓 `xxx.py`
2. 缁ф壙 `BaseImporter` 绫?3. 瀹炵幇 `detect()` 鍜?`parse()` 鏂规硶
4. 鍦?`ailog/importers/__init__.py` 娉ㄥ唽
5. 娣诲姞娴嬭瘯鐢ㄤ緥

鍙傝€冪ず渚嬶細`ailog/importers/chatgpt.py`

## 娣诲姞鏂板鍑哄櫒

1. 鍦?`ailog/exporters/` 鍒涘缓 `xxx.py`
2. 缁ф壙 `BaseExporter` 绫?3. 瀹炵幇 `export()` 鏂规硶
4. 鍦?`ailog/exporters/__init__.py` 娉ㄥ唽
5. 鍦?`cli.py` 鐨?`cmd_export` 娣诲姞鏀寔

鍙傝€冪ず渚嬶細`ailog/exporters/obsidian.py`

## 浠ｇ爜瑙勮寖

- 浣跨敤 Python 3.10+ 璇硶
- 浣跨敤 type hints
- 淇濇寔鍑芥暟绠€鐭紙<50 琛岋級
- 鎵€鏈夊叕鍏?API 闇€瑕佺被鍨嬫爣娉?
## 娴嬭瘯

```bash
# 杩愯鎵€鏈夋祴璇?python -m pytest ailog/tests/ -v

# 杩愯鍗曚釜娴嬭瘯
python -m pytest ailog/tests/test_chatgpt_importer.py -v
```

## 闂鍙嶉

- Bug 鎶ュ憡锛歨ttps://github.com/Mby159/ailog/issues
- 鍔熻兘寤鸿锛歨ttps://github.com/Mby159/ailog/discussions
