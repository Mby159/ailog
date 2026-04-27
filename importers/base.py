"""
AILog BaseImporter — Abstract base class for all platform importers.

Every importer converts a platform-specific format into AILogFile.
Subclasses must implement:
  - platform_id: str (registered platform ID)
  - detect(source_path) -> bool
  - parse(source_path) -> AILogFile
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ailog.core.models import (
    AILogFile,
    AILogFileMetadata,
    OwnerInfo,
    OwnerIdType,
)


class BaseImporter(ABC):
    """Abstract base class for AILog importers."""

    platform_id: str = "custom"
    platform_url: Optional[str] = None

    @abstractmethod
    def detect(self, source_path: str | Path) -> bool:
        """
        Detect if the source file/directory is from this platform.

        Args:
            source_path: Path to the source file or directory

        Returns:
            True if this importer can handle the source
        """
        ...

    @abstractmethod
    def parse(self, source_path: str | Path) -> AILogFile:
        """
        Parse the source into an AILogFile.

        Args:
            source_path: Path to the source file or directory

        Returns:
            AILogFile with all interactions populated
        """
        ...

    def _build_metadata(
        self,
        owner: Optional[OwnerInfo] = None,
        tags: Optional[list[str]] = None,
        custom: Optional[dict] = None,
    ) -> AILogFileMetadata:
        """Build standard AILogFileMetadata for this importer."""
        return AILogFileMetadata(
            source_platform=self.platform_id,
            source_url=self.platform_url,
            export_timestamp=datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            exporter=f"ailog-importer-{self.platform_id}/0.1.0",
            owner=owner or OwnerInfo(id_type=OwnerIdType.ANONYMOUS),
            tags=tags or [],
            custom=custom or {},
        )
