"""Shared data models for the content pipeline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UploadResult:
    """Result of uploading chapters to a notebook."""

    id: str
    title: str
    chapters: int


@dataclass
class NotebookInfo:
    """Summary of a NotebookLM notebook."""

    id: str
    title: str
    sources_count: int


@dataclass
class SourceInfo:
    """Summary of a source within a notebook."""

    id: str
    title: str
