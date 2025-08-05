#!/usr/bin/env python3
"""
Development server for MCP SQLAlchemy Server

This module is specifically for development and testing with `mcp dev`.
It exposes a server object that can be used with the MCP Inspector.
"""

import os

from dotenv import load_dotenv

from mcp_sqlalchemy.server import (
    DEFAULT_MAX_QUERY_TIMEOUT,
    DEFAULT_MAX_RESULT_ROWS,
    SQLAlchemyMCP,
)

# Load environment variables
load_dotenv()

# Get configuration from environment variables
database_url = os.getenv("DATABASE_URL") or os.getenv("DB_URL") or "sqlite:///./test.db"

# Security configuration with fallbacks
max_query_timeout = int(
    os.getenv("MCP_MAX_QUERY_TIMEOUT", str(DEFAULT_MAX_QUERY_TIMEOUT))
)

max_result_rows = int(os.getenv("MCP_MAX_RESULT_ROWS", str(DEFAULT_MAX_RESULT_ROWS)))

read_only_mode = os.getenv("MCP_READ_ONLY", "true").lower() in (
    "true",
    "1",
    "yes",
    "on",
)

# Create the MCP server instance for development
mcp = SQLAlchemyMCP(
    name="SQLAlchemy Database (Dev)",
    database_url=database_url,
    max_query_timeout=max_query_timeout,
    max_result_rows=max_result_rows,
    read_only_mode=read_only_mode,
)
