"""Canonical JSON (CJSON) -- AILog 哈希域规范化参考实现.

规范见 ``spec/FORMAT.md`` 的 "Canonical JSON（哈希域规范化）" 一节。

所有进入**哈希域**（Merkle leaf、anchor、proof bundle）的数据都必须先经
:func:`canonical_json` 序列化。任何宿主语言的默认 JSON 序列化
（``json.dumps()`` / ``JSON.stringify()``）**都不满足本规范**，禁止直接使用。

规则摘要::

    C1  UTF-8，无 BOM
    C2  对象键递归按 Unicode 码点升序；数组顺序保持
    C3  无多余空白（分隔符为 "," 与 ":"，冒号后无空格）
    C4  仅转义 " \\ 与 U+0000-U+001F；非 ASCII 原样输出
    C5  只允许 |n| <= 2^53-1 的整数；浮点 / NaN / Infinity 一律拒绝
    C6  缺失字段省略，不写 null 占位
    C7  不允许重复键
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

__all__ = [
    "CanonicalJSONError",
    "MAX_SAFE_INTEGER",
    "canonical_json",
    "canonical_sha256",
    "loads_strict",
]

#: IEEE-754 双精度可精确表示的最大整数：2^53 - 1
MAX_SAFE_INTEGER = 2**53 - 1


class CanonicalJSONError(ValueError):
    """数据无法表示为 Canonical JSON。"""


def _reject(value: Any, reason: str, path: str) -> None:
    raise CanonicalJSONError(f"{reason} at {path or '$'}")


def _validate(value: Any, path: str = "") -> None:
    """C5 / C7 前置校验：拒绝浮点、越界整数、非字符串键。

    ``json.dumps`` 会静默产出非法 Canonical JSON，所以在序列化前显式拦截。
    """
    if value is None or isinstance(value, (bool, str)):
        if isinstance(value, str):
            # 孤立代理项无法编码为 UTF-8，直接拒绝
            try:
                value.encode("utf-8")
            except UnicodeEncodeError as exc:
                _reject(value, f"string is not UTF-8 encodable ({exc})", path)
        return

    if isinstance(value, float):
        _reject(value, "float is not allowed in the canonical domain (C5)", path)

    if isinstance(value, int):
        if not -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            _reject(
                value,
                f"integer outside +/-(2^53-1) is not representable (C5)",
                path,
            )
        return

    if isinstance(value, dict):
        seen: set = set()
        for key, item in value.items():
            if not isinstance(key, str):
                _reject(key, "object keys must be strings (C2)", path)
            if key in seen:
                _reject(key, "duplicate object key (C7)", path)
            seen.add(key)
            _validate(item, f"{path}.{key}")
        return

    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate(item, f"{path}[{index}]")
        return

    _reject(value, f"unsupported type {type(value).__name__}", path)


def canonical_json(value: Any) -> str:
    """把 ``value`` 序列化为 Canonical JSON 字符串（C1-C7）。"""
    _validate(value)
    return json.dumps(
        value,
        ensure_ascii=False,      # C4：非 ASCII 原样输出
        sort_keys=True,          # C2：Python 的 str 比较即码点序
        separators=(",", ":"),   # C3：无多余空白
        allow_nan=False,         # C5：NaN / Infinity 直接报错
    )


def canonical_bytes(value: Any) -> bytes:
    """Canonical JSON 的 UTF-8 字节串（C1）。"""
    return canonical_json(value).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    """Canonical JSON 字节串的 SHA-256 十六进制摘要。"""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _reject_duplicate_keys(pairs):
    seen: set = set()
    for key, _ in pairs:
        if key in seen:
            raise CanonicalJSONError(f"duplicate object key (C7): {key!r}")
        seen.add(key)
    return dict(pairs)


def loads_strict(text: str) -> Any:
    """解析 JSON，并对 C7（重复键）做强制校验。

    ``json.loads`` 默认让后者覆盖前者，会静默吞掉重复键。
    """
    return json.loads(text, object_pairs_hook=_reject_duplicate_keys)