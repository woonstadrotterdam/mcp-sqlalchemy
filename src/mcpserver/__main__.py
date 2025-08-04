#!/usr/bin/env python3
"""
MCP SQLAlchemy Server Entry Point

This allows the package to be run directly with:
uvx mcp-server

or

python -m mcpserver
"""
import argparse
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

from mcpserver.server import (
    DEFAULT_MAX_QUERY_TIMEOUT,
    DEFAULT_MAX_RESULT_ROWS,
    SQLAlchemyMCP,
)


def setup_logging(transport_mode: str = "stdio"):
    """Setup logging configuration based on transport mode."""
    # Configure logging to stderr to avoid interfering with stdio protocol
    log_level = os.getenv("MCP_LOG_LEVEL", "INFO").upper()

    # In stdio mode, we must use stderr to avoid interfering with protocol
    # In HTTP mode, we can be more flexible
    if transport_mode == "stdio":
        handler = logging.StreamHandler(sys.stderr)
        # More minimal format for stdio mode
        formatter = logging.Formatter("%(levelname)s: %(message)s")
    else:
        handler = logging.StreamHandler(sys.stdout)
        # More detailed format for HTTP mode
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

    handler.setFormatter(formatter)

    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO), handlers=[handler], force=True
    )

    return logging.getLogger(__name__)


def main():
    """Main entry point for the MCP SQLAlchemy Server"""
    load_dotenv()

    parser = argparse.ArgumentParser(description="MCP SQLAlchemy Server")
    parser.add_argument(
        "--database-url",
        help="SQLAlchemy connection URL (or set DATABASE_URL/DB_URL environment variable)",
    )
    parser.add_argument(
        "--name", default="SQLAlchemy Database", help="Name for the MCP server"
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Run server with streamable HTTP transport instead of stdio",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="HTTP server port (default: 8000, only used with --http)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="HTTP server host (default: 127.0.0.1, only used with --http)",
    )
    parser.add_argument(
        "--stateless",
        action="store_true",
        help="Run HTTP server in stateless mode (only used with --http)",
    )

    # Security configuration options
    parser.add_argument(
        "--max-query-timeout",
        type=int,
        help=f"Maximum query execution time in seconds (default: {DEFAULT_MAX_QUERY_TIMEOUT}, or set MCP_MAX_QUERY_TIMEOUT)",
    )
    parser.add_argument(
        "--max-result-rows",
        type=int,
        help=f"Maximum number of rows to return (default: {DEFAULT_MAX_RESULT_ROWS}, or set MCP_MAX_RESULT_ROWS)",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Enable read-only mode - only allow SELECT queries (or set MCP_READ_ONLY=true)",
    )

    args = parser.parse_args()

    # Setup logging based on transport mode
    transport_mode = "http" if args.http else "stdio"
    logger = setup_logging(transport_mode)

    # Prioritize command line args over environment variables
    database_url = args.database_url or os.getenv("DATABASE_URL") or os.getenv("DB_URL")

    if not database_url:
        parser.error(
            "Database URL must be provided with --database-url or by setting the DATABASE_URL/DB_URL environment variable"
        )

    # Security configuration with fallbacks
    max_query_timeout = args.max_query_timeout
    if max_query_timeout is None:
        max_query_timeout = int(
            os.getenv("MCP_MAX_QUERY_TIMEOUT", str(DEFAULT_MAX_QUERY_TIMEOUT))
        )

    max_result_rows = args.max_result_rows
    if max_result_rows is None:
        max_result_rows = int(
            os.getenv("MCP_MAX_RESULT_ROWS", str(DEFAULT_MAX_RESULT_ROWS))
        )

    read_only_mode = args.read_only
    if not read_only_mode:
        read_only_mode = os.getenv("MCP_READ_ONLY", "true").lower() in (
            "true",
            "1",
            "yes",
            "on",
        )

    # Create the MCP server with appropriate transport settings
    # Only pass port if HTTP mode is enabled
    server_kwargs = {
        "name": args.name,
        "database_url": database_url,
        "host": args.host,
        "stateless_http": args.stateless,
        "max_query_timeout": max_query_timeout,
        "max_result_rows": max_result_rows,
        "read_only_mode": read_only_mode,
    }

    # Only add port if we're using HTTP transport
    if args.http:
        server_kwargs["port"] = args.port

    mcp = SQLAlchemyMCP(**server_kwargs)

    # Log configuration info
    logger.info("Starting MCP SQLAlchemy Server")
    logger.info(f"Name: {args.name}")
    logger.info(
        f"Database URL: {database_url[:20]}{'...' if len(database_url) > 20 else ''}"
    )
    logger.info(f"Transport: {'HTTP' if args.http else 'stdio'}")
    if args.http:
        logger.info(f"Host: {args.host}:{args.port}")
        logger.info(f"Stateless: {args.stateless}")
    logger.info("Security Settings:")
    logger.info(f"  Max Query Timeout: {max_query_timeout}s")
    logger.info(f"  Max Result Rows: {max_result_rows}")
    logger.info(f"  Read-Only Mode: {read_only_mode}")

    # Run the server
    try:
        mcp.run(transport="streamable-http" if args.http else "stdio")
    except KeyboardInterrupt:
        logger.info("Shutting down server...")
    finally:
        # Clean up the server resources
        if hasattr(mcp, "close"):
            asyncio.run(mcp.close())


if __name__ == "__main__":
    main()
