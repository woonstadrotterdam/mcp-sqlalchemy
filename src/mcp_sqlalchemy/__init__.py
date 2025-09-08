"""
MCP SQLAlchemy Server Package

This package provides a Model Context Protocol (MCP) server for SQLAlchemy database interactions.
"""

from .server import (
    DEFAULT_MAX_QUERY_TIMEOUT,
    DEFAULT_MAX_RESULT_ROWS,
    DEFAULT_READ_ONLY_MODE,
    SQLAlchemyMCP,
)

__all__ = [
    "SQLAlchemyMCP",
    "DEFAULT_MAX_QUERY_TIMEOUT",
    "DEFAULT_MAX_RESULT_ROWS",
    "DEFAULT_READ_ONLY_MODE",
]

# Version information
__version__ = "0.2.1"
