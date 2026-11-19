"""ASGI entry point for hosts that support Vercel's Python/FastAPI runtime."""

from ems_backend.app import app

__all__ = ["app"]
