"""Deterministic, local EMS workbook processing."""

from .models import ProcessingResult
from .processor import process_workbook

__all__ = ["ProcessingResult", "process_workbook"]
