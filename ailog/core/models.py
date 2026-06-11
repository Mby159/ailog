"""
AILog Core Data Models v0.1
Platform-agnostic format for AI interaction artifacts.

Design principles:
  - Core fields minimal (7 required per Interaction)
  - Privacy annotation, not encryption (GhostGuard does the heavy lifting)
  - Artifacts are first-class citizens
  - JSONL-first, JSON fallback
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pathlib import Path


# ──────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────

class Role(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class ContentType(str, Enum):
    TEXT = "text"
    MARKDOWN = "markdown"
    HTML = "html"
    CODE = "code"
    IMAGE = "image"
    AUDIO = "audio"
    FILE = "file"


class ArtifactType(str, Enum):
    CODE = "code"
    IMAGE = "image"
    DOCUMENT = "document"
    DATA = "data"
    AUDIO = "audio"
    VIDEO = "video"
    OTHER = "other"


class RiskLevel(str, Enum):
    """Aligned with GhostGuard SensitivityLevel + privacy-proxy RiskLevel"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RedactionStrategy(str, Enum):
    """Aligned with GhostGuard RedactionStrategy"""
    PLACEHOLDER = "placeholder"
    MASK = "mask"
    REMOVE = "remove"
    HASH = "hash"


class OwnerIdType(str, Enum):
    EMAIL = "email"
    USERNAME = "username"
    ANONYMOUS = "anonymous"


# ──────────────────────────────────────────────
# Core Models
# ──────────────────────────────────────────────

@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class Message:
    role: Role
    content: str
    content_type: ContentType = ContentType.TEXT
    timestamp: Optional[str] = None          # ISO 8601
    model: Optional[str] = None
    model_provider: Optional[str] = None
    token_usage: Optional[TokenUsage] = None
    custom: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["role"] = self.role.value
        d["content_type"] = self.content_type.value
        if self.token_usage is None:
            del d["token_usage"]
        if not self.custom:
            del d["custom"]
        # Strip None values
        return {k: v for k, v in d.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        data = dict(data)
        data["role"] = Role(data["role"])
        data["content_type"] = ContentType(data.get("content_type", "text"))
        if "token_usage" in data and data["token_usage"]:
            data["token_usage"] = TokenUsage(**data["token_usage"])
        else:
            data["token_usage"] = None
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Artifact:
    id: str
    type: ArtifactType
    name: str
    content: Optional[str] = None
    url: Optional[str] = None
    language: Optional[str] = None
    size_bytes: Optional[int] = None
    hash: Optional[str] = None
    source_message_index: Optional[int] = None
    custom: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["type"] = self.type.value
        if not self.custom:
            del d["custom"]
        return {k: v for k, v in d.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Artifact":
        data = dict(data)
        data["type"] = ArtifactType(data["type"])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class SensitivityItem:
    """One detected sensitive item — aligned with GhostGuard DetectionResult."""
    info_type: str
    risk_level: RiskLevel
    field: str                              # JSONPath to the sensitive field
    redacted: bool = False
    strategy: Optional[RedactionStrategy] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["risk_level"] = self.risk_level.value
        if self.strategy:
            d["strategy"] = self.strategy.value
        else:
            del d["strategy"]
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SensitivityItem":
        data = dict(data)
        data["risk_level"] = RiskLevel(data["risk_level"])
        if "strategy" in data and data["strategy"]:
            data["strategy"] = RedactionStrategy(data["strategy"])
        else:
            data["strategy"] = None
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class SensitivityInfo:
    """Privacy annotation for an interaction — powered by GhostGuard."""
    max_risk_level: RiskLevel
    detected_items: List[SensitivityItem] = field(default_factory=list)
    scanned_by: Optional[str] = None
    scan_timestamp: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "max_risk_level": self.max_risk_level.value,
            "detected_items": [item.to_dict() for item in self.detected_items],
        }
        if self.scanned_by:
            d["scanned_by"] = self.scanned_by
        if self.scan_timestamp:
            d["scan_timestamp"] = self.scan_timestamp
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SensitivityInfo":
        data = dict(data)
        data["max_risk_level"] = RiskLevel(data["max_risk_level"])
        data["detected_items"] = [
            SensitivityItem.from_dict(item) for item in data.get("detected_items", [])
        ]
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Interaction:
    """Core unit: one turn of human-AI conversation."""
    id: str
    timestamp: str                           # ISO 8601
    session_id: str
    turn_index: int
    messages: List[Message]
    artifacts: List[Artifact] = field(default_factory=list)
    sensitivity: Optional[SensitivityInfo] = None
    custom: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "turn_index": self.turn_index,
            "messages": [m.to_dict() for m in self.messages],
        }
        if self.artifacts:
            d["artifacts"] = [a.to_dict() for a in self.artifacts]
        if self.sensitivity:
            d["sensitivity"] = self.sensitivity.to_dict()
        if self.custom:
            d["custom"] = self.custom
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Interaction":
        data = dict(data)
        data["messages"] = [Message.from_dict(m) for m in data["messages"]]
        data["artifacts"] = [Artifact.from_dict(a) for a in data.get("artifacts", [])]
        if "sensitivity" in data and data["sensitivity"]:
            data["sensitivity"] = SensitivityInfo.from_dict(data["sensitivity"])
        else:
            data["sensitivity"] = None
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class OwnerInfo:
    id: Optional[str] = None
    id_type: Optional[OwnerIdType] = None
    display_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {}
        if self.id is not None:
            d["id"] = self.id
        if self.id_type is not None:
            d["id_type"] = self.id_type.value
        if self.display_name is not None:
            d["display_name"] = self.display_name
        return d if d else {"id_type": "anonymous"}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OwnerInfo":
        data = dict(data)
        if "id_type" in data and data["id_type"]:
            data["id_type"] = OwnerIdType(data["id_type"])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class AILogFileMetadata:
    source_platform: str
    export_timestamp: str                    # ISO 8601
    exporter: str                            # name/version
    source_url: Optional[str] = None
    owner: Optional[OwnerInfo] = None
    tags: List[str] = field(default_factory=list)
    custom: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "source_platform": self.source_platform,
            "export_timestamp": self.export_timestamp,
            "exporter": self.exporter,
        }
        if self.source_url:
            d["source_url"] = self.source_url
        if self.owner:
            d["owner"] = self.owner.to_dict()
        if self.tags:
            d["tags"] = self.tags
        if self.custom:
            d["custom"] = self.custom
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AILogFileMetadata":
        data = dict(data)
        if "owner" in data and data["owner"]:
            data["owner"] = OwnerInfo.from_dict(data["owner"])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class AILogFile:
    """Complete .ailog file (JSON mode)."""
    ailog_version: str = "0.1"
    metadata: AILogFileMetadata = field(default_factory=lambda: AILogFileMetadata(
        source_platform="custom", export_timestamp="", exporter=""
    ))
    interactions: List[Interaction] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ailog_version": self.ailog_version,
            "metadata": self.metadata.to_dict(),
            "interactions": [i.to_dict() for i in self.interactions],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def to_jsonl(self) -> str:
        """Convert to JSONL format (one metadata line + one line per interaction)."""
        lines = []
        # First line: metadata
        meta_line = json.dumps({
            "ailog_version": self.ailog_version,
            "type": "metadata",
            "metadata": self.metadata.to_dict(),
        }, ensure_ascii=False)
        lines.append(meta_line)
        # Subsequent lines: interactions
        for interaction in self.interactions:
            ix_line = json.dumps({
                "ailog_version": self.ailog_version,
                "type": "interaction",
                **interaction.to_dict(),
            }, ensure_ascii=False)
            lines.append(ix_line)
        return "\n".join(lines)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AILogFile":
        data = dict(data)
        data["metadata"] = AILogFileMetadata.from_dict(data.get("metadata", {}))
        data["interactions"] = [
            Interaction.from_dict(i) for i in data.get("interactions", [])
        ]
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_json(cls, json_str: str) -> "AILogFile":
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def from_jsonl(cls, jsonl_str: str) -> "AILogFile":
        """Parse JSONL format into AILogFile."""
        metadata = None
        interactions = []
        for line in jsonl_str.strip().split("\n"):
            if not line.strip():
                continue
            obj = json.loads(line)
            if obj.get("type") == "metadata":
                metadata = AILogFileMetadata.from_dict(obj.get("metadata", {}))
            elif obj.get("type") == "interaction":
                interactions.append(Interaction.from_dict(obj))
        if metadata is None:
            metadata = AILogFileMetadata(
                source_platform="unknown",
                export_timestamp=datetime.utcnow().isoformat() + "Z",
                exporter="ailog-reader/0.1.0",
            )
        return cls(ailog_version="0.1", metadata=metadata, interactions=interactions)

    def save(self, path: str | Path, fmt: str = "jsonl") -> None:
        """Save to file. fmt: 'jsonl' (default) or 'json'."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "json":
            path.write_text(self.to_json(), encoding="utf-8")
        else:
            path.write_text(self.to_jsonl(), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "AILogFile":
        """Load from .ailog (JSONL) or .ailog.json (JSON) file."""
        path = Path(path)
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".json" or path.suffixes == [".ailog", ".json"]:
            return cls.from_json(text)
        else:
            # Try JSONL first, fallback to JSON
            if text.strip().startswith("{") and "\n{" not in text.strip()[:200]:
                try:
                    return cls.from_json(text)
                except json.JSONDecodeError:
                    pass
            return cls.from_jsonl(text)
