"""Expose the Flask application factory as backend.create_app."""
from backend.app_factory import create_app

__all__ = ["create_app"]
