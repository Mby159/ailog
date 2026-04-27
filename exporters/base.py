"""
AILog BaseExporter — Abstract base class for all exporters.

Exporters convert AILogFile into platform-specific formats:
  - Obsidian Markdown
  - Notion
  - PDF
  - HTML
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ailog.core.models import AILogFile


class BaseExporter(ABC):
    """Abstract base class for AILog exporters."""

    target_format: str = "custom"
    file_extension: str = ".txt"

    @abstractmethod
    def export(self, ailog: ALogFile, output_path: str | Path) -> Path:
        """
        Export ALogFile to target format.

        Args:
            ailog: The ALogFile to export
            output_path: Output file/directory path

        Returns:
            Path to the created output
        """
        ...

    @abstractmethod
    def export_string(self, ailog: ALogFile) -> str:
        """
        Export ALogFile to string (for preview/testing).

        Args:
            ailog: The ALogFile to export

        Returns:
            String representation in target format
        """
        ...
