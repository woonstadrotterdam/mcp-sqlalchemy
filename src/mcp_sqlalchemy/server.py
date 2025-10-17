"""
SQLAlchemy MCP Server
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Dict, List, Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from sqlalchemy import column, func, inspect, literal_column, select, table, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

# Load environment variables
load_dotenv()

# Default configuration values
DEFAULT_MAX_QUERY_TIMEOUT = 30
DEFAULT_MAX_RESULT_ROWS = 25
DEFAULT_READ_ONLY_MODE = True


class SQLAlchemyMCP(FastMCP):
    """MCP server for SQLAlchemy database interactions."""

    def __init__(
        self,
        name: str = "SQLAlchemy Database",
        database_url: Optional[str] = None,
        port: Optional[int] = None,
        host: str = "127.0.0.1",
        stateless_http: bool = False,
        max_query_timeout: int = DEFAULT_MAX_QUERY_TIMEOUT,
        max_result_rows: int = DEFAULT_MAX_RESULT_ROWS,
        read_only_mode: bool = DEFAULT_READ_ONLY_MODE,
    ):
        """
        Initialize SQLAlchemy MCP server.

        Args:
            name: Name of the MCP server
            database_url: SQLAlchemy connection URL
            port: Port to run the server on (only required for HTTP transport)
            host: Host to run the server on
            stateless_http: Whether to use stateless HTTP mode
            max_query_timeout: Maximum query execution time in seconds
            max_result_rows: Maximum number of rows to return
            read_only_mode: If True, only allow read operations
        """
        # Build FastMCP constructor arguments, only including port if provided
        fastmcp_kwargs = {"name": name, "stateless_http": stateless_http, "host": host}
        if port is not None:
            fastmcp_kwargs["port"] = port

        super().__init__(**fastmcp_kwargs)

        # Store security configuration
        self.max_query_timeout = max_query_timeout
        self.max_result_rows = max_result_rows
        self.read_only_mode = read_only_mode

        # Use provided database_url or get from environment
        self.database_url = (
            database_url or os.getenv("DATABASE_URL") or os.getenv("DB_URL")
        )
        if not self.database_url:
            raise ValueError(
                "Database URL must be provided or set as DATABASE_URL/DB_URL environment variable"
            )

        # Convert sync URL to async URL if needed
        if self.database_url.startswith("sqlite://"):
            # For SQLite (both file-based and in-memory), use aiosqlite driver
            self.database_url = self.database_url.replace(
                "sqlite://", "sqlite+aiosqlite://"
            )
        elif self.database_url.startswith("postgresql://"):
            self.database_url = self.database_url.replace(
                "postgresql://", "postgresql+asyncpg://"
            )
        elif self.database_url.startswith("mysql://"):
            self.database_url = self.database_url.replace(
                "mysql://", "mysql+aiomysql://"
            )

        # Prepare connection arguments - only PostgreSQL needs custom settings
        connect_args = {}

        # PostgreSQL-specific configuration
        if "postgresql" in self.database_url:
            # Get the schema name for setting search path
            schema_name = os.getenv("DB_SCHEMA_NAME")

            server_settings = {
                "application_name": "mcp_sqlalchemy",
                "jit": "off",  # Disable JIT compilation for better performance in short-lived connections
                "statement_timeout": str(
                    self.max_query_timeout * 1000
                ),  # PostgreSQL statement timeout in milliseconds
            }

            # Set search path if schema is specified
            if schema_name:
                server_settings["search_path"] = schema_name

            connect_args = {
                "server_settings": server_settings,
                "command_timeout": self.max_query_timeout,  # asyncpg query timeout
            }
        # SQLite and MySQL use driver defaults (no custom connect_args needed)

        self.engine = create_async_engine(
            self.database_url,
            connect_args=connect_args,
        )

        # Store database type for timeout handling
        self.is_mysql = self.database_url.startswith(
            ("mysql+aiomysql://", "mysql+asyncmy://")
        )
        self.is_sqlite = self.database_url.startswith("sqlite+aiosqlite://")

        # Register resources and tools
        self._register_resources()
        self._register_tools()

    def _validate_identifier(self, name: str) -> bool:
        """Validate SQL identifier to prevent injection."""
        if not name or not isinstance(name, str):
            return False
        # Allow alphanumeric, underscore, and dots for schema.table notation
        return bool(re.match(r"^[a-zA-Z_][a-zA-Z0-9_.]*$", name))

    def _validate_limit(self, limit: int) -> int:
        """Validate and cap limit parameter."""
        if not isinstance(limit, int) or limit < 1:
            return 10
        return min(limit, self.max_result_rows)

    def _is_read_only_query(self, sql: str) -> bool:
        """Check if query is read-only."""
        if not sql or not isinstance(sql, str):
            return False

        sql_lower = sql.strip().lower()
        # Remove comments and normalize whitespace
        sql_lower = re.sub(r"--.*", "", sql_lower)
        sql_lower = re.sub(r"/\*.*?\*/", "", sql_lower, flags=re.DOTALL)
        sql_lower = " ".join(sql_lower.split())

        read_only_patterns = ["select", "show", "describe", "explain", "with"]
        destructive_patterns = [
            "insert",
            "update",
            "delete",
            "drop",
            "create",
            "alter",
            "truncate",
            "grant",
            "revoke",
        ]

        for pattern in destructive_patterns:
            if sql_lower.startswith(pattern):
                return False

        return any(sql_lower.startswith(pattern) for pattern in read_only_patterns)

    async def _setup_mysql_session(self, connection):
        """Set up MySQL session with execution timeout."""
        if self.is_mysql:
            # Set max_execution_time in milliseconds
            timeout_ms = self.max_query_timeout * 1000
            await connection.execute(
                text(f"SET SESSION max_execution_time = {timeout_ms}")
            )

    async def _execute_with_timeout(self, connection, query):
        """Execute query with appropriate timeout handling based on database type."""
        if self.is_sqlite:
            # For SQLite, use asyncio.wait_for since it has no server-side timeout
            return await asyncio.wait_for(
                connection.execute(query), timeout=self.max_query_timeout
            )
        else:
            # For PostgreSQL and MySQL, rely on server-side timeouts
            return await connection.execute(query)

    async def _safe_execute(self, operation, *args, **kwargs):
        """Wrapper for safe database operations with error handling."""
        try:
            return await operation(*args, **kwargs)
        except SQLAlchemyError as e:
            logging.error(f"Database error: {e}")
            return {"error": f"Database error: {str(e)}"}
        except Exception as e:
            logging.error(f"Unexpected error: {e}")
            return {"error": f"Unexpected error: {str(e)}"}

    async def close(self):
        """Clean up resources when shutting down."""
        await self.engine.dispose()

    def _register_resources(self):
        """Register all resources for this MCP server."""

        @self.resource("schema://")
        async def get_schema_list() -> str:
            """List all schemas in the database."""
            async with self.engine.connect() as conn:

                def get_schemas(sync_conn):
                    inspector = inspect(sync_conn)
                    return inspector.get_schema_names()

                schemas = await conn.run_sync(get_schemas)
                return "\n".join(f"- {schema}" for schema in schemas)

        @self.resource("schema://{schema_name}")
        async def get_schema(schema_name: str) -> str:
            """Get schema details for a specific schema."""
            # Validate inputs
            if not self._validate_identifier(schema_name):
                return f"Error: Invalid schema name '{schema_name}'"

            try:
                async with self.engine.connect() as conn:

                    def get_tables(sync_conn):
                        inspector = inspect(sync_conn)
                        return inspector.get_table_names(schema=schema_name)

                    tables = await conn.run_sync(get_tables)
                    result = [f"Schema: {schema_name}", "Tables:"]
                    for table in tables:
                        result.append(f"- {table}")
                    return "\n".join(str(item) for item in result)
            except SQLAlchemyError as e:
                return f"Database error: {str(e)}"
            except Exception as e:
                return f"Error: {str(e)}"

        @self.resource("table://{schema_name}/{table_name}")
        async def get_table_info(schema_name: str, table_name: str) -> str:
            """Get detailed information about a specific table."""
            # Validate inputs
            if not self._validate_identifier(schema_name):
                return f"Error: Invalid schema name '{schema_name}'"
            if not self._validate_identifier(table_name):
                return f"Error: Invalid table name '{table_name}'"

            try:
                async with self.engine.connect() as conn:

                    def get_table_details(sync_conn):
                        inspector = inspect(sync_conn)
                        # Get table columns
                        columns = inspector.get_columns(table_name, schema=schema_name)
                        # Get primary keys
                        pk_constraint = inspector.get_pk_constraint(
                            table_name, schema=schema_name
                        )
                        # Get foreign keys
                        foreign_keys = inspector.get_foreign_keys(
                            table_name, schema=schema_name
                        )
                        # Get indexes
                        indexes = inspector.get_indexes(table_name, schema=schema_name)

                        return {
                            "columns": columns,
                            "pk_constraint": pk_constraint,
                            "foreign_keys": foreign_keys,
                            "indexes": indexes,
                        }

                    table_info = await conn.run_sync(get_table_details)

                    # Build response
                    result = [f"Table: {schema_name}.{table_name}", "\nColumns:"]
                    for col in table_info["columns"]:
                        pk_flag = (
                            "*"
                            if col["name"]
                            in table_info["pk_constraint"].get(
                                "constrained_columns", []
                            )
                            else ""
                        )
                        result.append(f"- {col['name']}{pk_flag}: {col['type']}")

                    if table_info["pk_constraint"] and table_info["pk_constraint"].get(
                        "constrained_columns"
                    ):
                        result.append("\nPrimary Key:")
                        result.append(
                            f"- {table_info['pk_constraint'].get('name', 'unnamed')}: {', '.join(table_info['pk_constraint']['constrained_columns'])}"
                        )

                    if table_info["foreign_keys"]:
                        result.append("\nForeign Keys:")
                        for fk in table_info["foreign_keys"]:
                            referred = f"{fk.get('referred_schema', schema_name)}.{fk['referred_table']}"
                            result.append(
                                f"- {fk.get('name', 'unnamed')}: {', '.join(fk['constrained_columns'])} -> {referred} ({', '.join(fk['referred_columns'])})"
                            )

                    if table_info["indexes"]:
                        result.append("\nIndexes:")
                        for idx in table_info["indexes"]:
                            unique = "UNIQUE " if idx.get("unique", False) else ""
                            column_names = [
                                name for name in idx["column_names"] if name is not None
                            ]
                            result.append(
                                f"- {unique}{idx['name']}: {', '.join(column_names)}"
                            )

                    return "\n".join(str(item) for item in result)
            except SQLAlchemyError as e:
                return f"Database error: {str(e)}"
            except Exception as e:
                return f"Error: {str(e)}"

        @self.resource("tables://{schema_name}")
        async def list_tables(schema_name: str) -> str:
            """List all tables in a specific schema."""
            # Validate inputs
            if not self._validate_identifier(schema_name):
                return f"Error: Invalid schema name '{schema_name}'"

            try:
                async with self.engine.connect() as conn:

                    def get_tables_and_views(sync_conn):
                        inspector = inspect(sync_conn)
                        tables = inspector.get_table_names(schema=schema_name)
                        views = inspector.get_view_names(schema=schema_name)
                        return {"tables": tables, "views": views}

                    table_data = await conn.run_sync(get_tables_and_views)

                    result = []
                    if table_data["tables"]:
                        result.append("Tables:")
                        for table in table_data["tables"]:
                            result.append(f"- {table}")

                    if table_data["views"]:
                        if result:
                            result.append("")
                        result.append("Views:")
                        for view in table_data["views"]:
                            result.append(f"- {view}")

                    return (
                        "\n".join(str(item) for item in result)
                        if result
                        else f"No tables or views found in schema {schema_name}"
                    )
            except SQLAlchemyError as e:
                return f"Database error: {str(e)}"
            except Exception as e:
                return f"Error: {str(e)}"

    def _register_tools(self):
        """Register all tools for this MCP server."""

        @self.tool(
            annotations=ToolAnnotations(
                destructiveHint=False,
                readOnlyHint=True,
                openWorldHint=False,
                title="Execute read-only query",
            )
        )
        async def execute_read_query(sql: str) -> str:
            """
            Execute a read-only SQL query (SELECT, SHOW, DESCRIBE, EXPLAIN) and return the results.
            This is the safer option for most query operations.

            Args:
                sql: The SQL query to execute (must be read-only)

            Returns:
                String representation of the query results
            """
            if not sql or not isinstance(sql, str):
                return "Error: Invalid SQL query provided."

            # Enforce read-only queries
            if not self._is_read_only_query(sql):
                return "Error: Only read-only queries (SELECT, SHOW, DESCRIBE, EXPLAIN, WITH) are allowed in this tool. Use execute_query for write operations."

            try:
                async with self.engine.connect() as connection:
                    # Set up MySQL session timeout if needed
                    await self._setup_mysql_session(connection)

                    # Execute query with appropriate timeout handling
                    result = await self._execute_with_timeout(connection, text(sql))

                    # Only handle SELECT-type queries that return rows
                    if result.returns_rows:
                        rows = result.fetchmany(self.max_result_rows)
                        if not rows:
                            return "Query executed successfully. No rows returned."

                        # Get column names
                        columns = result.keys()

                        # Format as table
                        table_data = [", ".join(str(col) for col in columns)]
                        table_data.append(
                            "-" * sum(len(str(col)) + 2 for col in columns)
                        )

                        # Add rows
                        for row in rows:
                            table_data.append(
                                ", ".join(
                                    str(val) if val is not None else "NULL"
                                    for val in row
                                )
                            )

                        # Check if there are more rows
                        more_rows_msg = ""
                        if len(rows) == self.max_result_rows:
                            more_rows_msg = f"\n\nNote: Results limited to {self.max_result_rows} rows. There may be additional rows."

                        return (
                            f"Query executed successfully. {len(rows)} rows returned.{more_rows_msg}\n\n"
                            + "\n".join(str(item) for item in table_data)
                        )
                    else:
                        return "Query executed successfully."
            except asyncio.TimeoutError:
                return f"Query timeout: Query execution exceeded {self.max_query_timeout} seconds"
            except SQLAlchemyError as e:
                return f"Database error: {str(e)}"
            except Exception as e:
                return f"Unexpected error: {str(e)}"

        @self.tool(
            annotations=ToolAnnotations(
                destructiveHint=True,
                readOnlyHint=False,
                openWorldHint=False,
                title="Execute query (with write access)",
            )
        )
        async def execute_query(sql: str) -> str:
            """
            Execute a SQL query with full write access (INSERT, UPDATE, DELETE, DDL).

            ⚠️  WARNING: This tool can modify or delete data. Use execute_read_query for safer read-only operations.

            This tool supports all SQL operations including:
            - Data modification (INSERT, UPDATE, DELETE)
            - Schema changes (CREATE, ALTER, DROP)
            - Data retrieval (SELECT)

            Args:
                sql: The SQL query to execute

            Returns:
                String representation of the query results
            """
            if not sql or not isinstance(sql, str):
                return "Error: Invalid SQL query provided."

            # Check if read-only mode is enabled and query is not read-only
            if self.read_only_mode and not self._is_read_only_query(sql):
                return "Error: Only read-only queries are allowed in read-only mode."

            try:
                async with self.engine.connect() as connection:
                    # Set up MySQL session timeout if needed
                    await self._setup_mysql_session(connection)

                    # Execute query with transaction management
                    async with connection.begin():
                        result = await self._execute_with_timeout(connection, text(sql))

                        # Check if result has returning data (like SELECT)
                        if result.returns_rows:
                            # For queries that return rows
                            rows = result.fetchmany(self.max_result_rows)
                            if not rows:
                                return "Query executed successfully. No rows returned."

                            # Get column names
                            columns = result.keys()

                            # Format as table
                            table_data = [", ".join(str(col) for col in columns)]
                            table_data.append(
                                "-" * sum(len(str(col)) + 2 for col in columns)
                            )

                            # Add rows
                            for row in rows:
                                table_data.append(
                                    ", ".join(
                                        str(val) if val is not None else "NULL"
                                        for val in row
                                    )
                                )

                            # Check if there are more rows
                            more_rows_msg = ""
                            if len(rows) == self.max_result_rows:
                                more_rows_msg = f"\n\nNote: Results limited to {self.max_result_rows} rows. There may be additional rows."

                            return (
                                f"Query executed successfully. {len(rows)} rows returned.{more_rows_msg}\n\n"
                                + "\n".join(str(item) for item in table_data)
                            )
                        else:
                            # For statements without returning rows (DML/DDL statements)
                            # Check for rowcount support
                            if hasattr(result, "rowcount") and result.rowcount >= 0:
                                # Different message formats based on rowcount
                                if result.rowcount == 0:
                                    return (
                                        "Query executed successfully. No rows affected."
                                    )
                                elif result.rowcount == 1:
                                    return (
                                        "Query executed successfully. 1 row affected."
                                    )
                                else:
                                    return f"Query executed successfully. {result.rowcount} rows affected."
                            else:
                                # Generic success message for other operations (like DDL)
                                return "Query executed successfully."
            except asyncio.TimeoutError:
                return f"Query timeout: Query execution exceeded {self.max_query_timeout} seconds"
            except SQLAlchemyError as e:
                return f"Database error: {str(e)}"
            except Exception as e:
                return f"Unexpected error: {str(e)}"

        @self.tool(
            annotations=ToolAnnotations(
                destructiveHint=False,
                readOnlyHint=True,
                openWorldHint=False,
                title="List schemas",
            )
        )
        async def list_schemas() -> str:
            """
            List all schemas in the database.

            Returns:
                String listing of all available schemas
            """
            try:
                async with self.engine.connect() as conn:

                    def get_schemas(sync_conn):
                        inspector = inspect(sync_conn)
                        return inspector.get_schema_names()

                    schemas = await conn.run_sync(get_schemas)

                    if not schemas:
                        return "No schemas found in database."

                    result = ["Available schemas:"]
                    for schema in schemas:
                        result.append(f"- {schema}")

                    return "\n".join(str(item) for item in result)
            except SQLAlchemyError as e:
                return f"Database error: {str(e)}"
            except Exception as e:
                return f"Error: {str(e)}"

        @self.tool(
            annotations=ToolAnnotations(
                destructiveHint=False,
                readOnlyHint=True,
                openWorldHint=False,
                title="Get table relationships",
            )
        )
        async def get_table_relationships() -> str:
            """
            Get a description of relationships between tables across the database.

            This provides a clear description of how tables are related through foreign keys,
            which helps in understanding the data model structure.

            Returns:
                String representation of table relationships
            """
            try:
                async with self.engine.connect() as conn:

                    def get_relationships(sync_conn):
                        inspector = inspect(sync_conn)
                        schemas = inspector.get_schema_names()

                        if not schemas:
                            return {
                                "schemas": [],
                                "error": "No schemas found in database.",
                            }

                        # Focus on relationships between tables
                        result = []

                        for schema in schemas:
                            # First, collect foreign key information for all tables in this schema
                            tables = inspector.get_table_names(schema=schema)

                            if not tables:
                                continue

                            # Only display schema information if tables exist
                            result.append(f"\nSchema: {schema}")

                            # Build a relationship map
                            relationships: Dict[
                                str, Dict[str, List[Dict[str, str]]]
                            ] = {}

                            # For each table, gather its inbound and outbound foreign keys
                            for table in tables:
                                fkeys_outbound = inspector.get_foreign_keys(
                                    table, schema=schema
                                )

                                # Store outbound relationships (this table references others)
                                if table not in relationships:
                                    relationships[table] = {
                                        "references": [],
                                        "referenced_by": [],
                                    }

                                for fk in fkeys_outbound:
                                    ref_schema = fk["referred_schema"] or schema
                                    ref_table = fk["referred_table"]
                                    source_cols = ", ".join(fk["constrained_columns"])
                                    target_cols = ", ".join(fk["referred_columns"])

                                    # Add outbound relationship
                                    relationships[table]["references"].append(
                                        {
                                            "table": ref_table,
                                            "schema": ref_schema,
                                            "source_columns": source_cols,
                                            "target_columns": target_cols,
                                        }
                                    )

                                    # Add corresponding inbound relationship to referenced table
                                    if (
                                        ref_schema == schema
                                    ):  # Only track inbound for same schema
                                        if ref_table not in relationships:
                                            relationships[ref_table] = {
                                                "references": [],
                                                "referenced_by": [],
                                            }

                                        relationships[ref_table][
                                            "referenced_by"
                                        ].append(
                                            {
                                                "table": table,
                                                "source_columns": source_cols,
                                                "target_columns": target_cols,
                                            }
                                        )

                            # Display relationships for each table
                            for table_name, table_info in sorted(relationships.items()):
                                result.append(f"\n  Table: {table_name}")

                                # Show outbound references (this table → others)
                                if table_info["references"]:
                                    result.append("    References (outbound):")
                                    for ref in table_info["references"]:
                                        if ref["schema"] != schema:
                                            result.append(
                                                f"      → {ref['schema']}.{ref['table']} "
                                                + f"({ref['source_columns']} → {ref['target_columns']})"
                                            )
                                        else:
                                            result.append(
                                                f"      → {ref['table']} "
                                                + f"({ref['source_columns']} → {ref['target_columns']})"
                                            )
                                else:
                                    result.append(
                                        "    References: None (independent table)"
                                    )

                                # Show inbound references (others → this table)
                                if table_info["referenced_by"]:
                                    result.append("    Referenced By (inbound):")
                                    for ref in table_info["referenced_by"]:
                                        result.append(
                                            f"      ← {ref['table']} "
                                            + f"({ref['target_columns']} ← {ref['source_columns']})"
                                        )
                                else:
                                    result.append(
                                        "    Referenced By: None (no dependencies)"
                                    )
                        if not result:
                            return {
                                "result": [
                                    "No pre-defined foreign key relationships found."
                                ]
                            }

                        result = [
                            "Table Relationships (Foreign Key Structure):"
                        ] + result
                        return {"result": result}

                    relationship_data = await conn.run_sync(get_relationships)

                    if "error" in relationship_data:
                        return relationship_data["error"]

                    return "\n".join(relationship_data["result"])
            except SQLAlchemyError as e:
                return f"Database error: {str(e)}"
            except Exception as e:
                return f"Error: {str(e)}"

        @self.tool(
            annotations=ToolAnnotations(
                destructiveHint=False,
                readOnlyHint=True,
                openWorldHint=False,
                title="List Tables",
            )
        )
        async def list_tables(schema_name: Optional[str] = None) -> str:
            """
            List all tables in the database or in a specific schema.

            Args:
                schema_name: Optional schema name to filter tables

            Returns:
                String listing of tables
            """
            # Validate inputs
            if schema_name and not self._validate_identifier(schema_name):
                return f"Error: Invalid schema name '{schema_name}'"

            try:
                async with self.engine.connect() as conn:

                    def get_tables(sync_conn):
                        inspector = inspect(sync_conn)
                        result = []

                        if schema_name:
                            # List tables in specific schema
                            tables = inspector.get_table_names(schema=schema_name)
                            if not tables:
                                return {
                                    "result": [],
                                    "message": f"No tables found in schema '{schema_name}'.",
                                }

                            result.append(f"Tables in schema '{schema_name}':")
                            for table in tables:
                                result.append(f"- {table}")
                        else:
                            # List tables in all schemas
                            schemas = inspector.get_schema_names()
                            for schema in schemas:
                                tables = inspector.get_table_names(schema=schema)
                                if tables:
                                    result.append(f"\nTables in schema '{schema}':")
                                    for table in tables:
                                        result.append(f"- {table}")

                        return {
                            "result": result,
                            "message": "\n".join(str(item) for item in result)
                            if result
                            else "No tables found.",
                        }

                    table_data = await conn.run_sync(get_tables)
                    return table_data["message"]
            except SQLAlchemyError as e:
                return f"Database error: {str(e)}"
            except Exception as e:
                return f"Error: {str(e)}"

        @self.tool(
            annotations=ToolAnnotations(
                destructiveHint=False,
                readOnlyHint=True,
                openWorldHint=False,
                title="Describe table",
            )
        )
        async def describe_table(
            table_name: str, schema_name: Optional[str] = None
        ) -> str:
            """
            Describe a table's structure.

            Args:
                table_name: Name of the table to describe
                schema_name: Optional schema name

            Returns:
                String description of the table structure
            """
            # Validate inputs
            if not self._validate_identifier(table_name):
                return f"Error: Invalid table name '{table_name}'"

            if schema_name and not self._validate_identifier(schema_name):
                return f"Error: Invalid schema name '{schema_name}'"

            try:
                async with self.engine.connect() as conn:

                    def get_table_structure(sync_conn):
                        inspector = inspect(sync_conn)

                        # Get table columns
                        columns = inspector.get_columns(table_name, schema=schema_name)
                        if not columns:
                            return {"error": f"Table '{table_name}' not found."}

                        # Get primary keys
                        pk_constraint = inspector.get_pk_constraint(
                            table_name, schema=schema_name
                        )
                        pk_columns = (
                            pk_constraint.get("constrained_columns", [])
                            if pk_constraint
                            else []
                        )

                        # Get foreign keys
                        fk_constraints = inspector.get_foreign_keys(
                            table_name, schema=schema_name
                        )

                        return {
                            "columns": columns,
                            "pk_columns": pk_columns,
                            "fk_constraints": fk_constraints,
                        }

                    table_data = await conn.run_sync(get_table_structure)

                    if "error" in table_data:
                        return table_data["error"]

                    # Format response
                    result = [
                        f"Table: {schema_name + '.' if schema_name else ''}{table_name}",
                        "\nColumns:",
                    ]
                    for col in table_data["columns"]:
                        pk_marker = (
                            " (PK)" if col["name"] in table_data["pk_columns"] else ""
                        )
                        nullable = "" if col.get("nullable", True) else " NOT NULL"
                        result.append(
                            f"- {col['name']}{pk_marker}: {col['type']}{nullable}"
                        )

                    if table_data["fk_constraints"]:
                        result.append("\nForeign Keys:")
                        for fk in table_data["fk_constraints"]:
                            referred_table = fk.get("referred_table", "")
                            referred_schema = fk.get("referred_schema", "")
                            referred_table_full = (
                                f"{referred_schema}.{referred_table}"
                                if referred_schema
                                else referred_table
                            )
                            constrained_columns = ", ".join(
                                fk.get("constrained_columns", [])
                            )
                            referred_columns = ", ".join(fk.get("referred_columns", []))
                            result.append(
                                f"- {constrained_columns} -> {referred_table_full}({referred_columns})"
                            )
                    return "\n".join(str(item) for item in result)
            except SQLAlchemyError as e:
                return f"Database error: {str(e)}"
            except Exception as e:
                return f"Error: {str(e)}"

        @self.tool(
            annotations=ToolAnnotations(
                destructiveHint=False,
                readOnlyHint=True,
                openWorldHint=False,
                title="Get table data",
            )
        )
        async def get_table_data(
            table_name: str, schema_name: Optional[str] = None, limit: int = 10
        ) -> str:
            """
            Get sample data from a table.

            Args:
                table_name: Name of the table
                schema_name: Optional schema name
                limit: Maximum number of rows to return (default: 10)

            Returns:
                String representation of table data
            """
            # Validate inputs
            if not self._validate_identifier(table_name):
                return f"Error: Invalid table name '{table_name}'"

            if schema_name and not self._validate_identifier(schema_name):
                return f"Error: Invalid schema name '{schema_name}'"

            # Validate and cap limit
            limit = self._validate_limit(limit)

            try:
                async with self.engine.connect() as conn:
                    # Build safe query using SQLAlchemy constructs
                    table_obj = table(table_name, schema=schema_name)
                    stmt = (
                        select(literal_column("*")).select_from(table_obj).limit(limit)
                    )

                    result = await conn.execute(stmt)
                    rows = result.fetchall()

                    table_ref = (
                        f"{schema_name}.{table_name}" if schema_name else table_name
                    )
                    if not rows:
                        return f"No data found in table {table_ref}."

                    # Format output
                    columns = result.keys()
                    table_output = [", ".join(str(col) for col in columns)]
                    table_output.append("-" * sum(len(str(col)) + 2 for col in columns))

                    for row in rows:
                        table_output.append(
                            ", ".join(
                                str(val) if val is not None else "NULL" for val in row
                            )
                        )

                    return (
                        f"Sample data from {table_ref} (limit {limit}):\n\n"
                        + "\n".join(str(item) for item in table_output)
                    )
            except SQLAlchemyError as e:
                return f"Database error: {str(e)}"
            except Exception as e:
                return f"Error: {str(e)}"

        @self.tool(
            annotations=ToolAnnotations(
                destructiveHint=False,
                readOnlyHint=True,
                openWorldHint=False,
                title="Get unique values",
            )
        )
        async def get_unique_values(
            table_name: str,
            column_name: str,
            schema_name: Optional[str] = None,
            limit: int = DEFAULT_MAX_RESULT_ROWS,
        ) -> str:
            """
            Get unique values from a specific column in a table. This is useful for understanding what values can be used in WHERE clauses.

            Args:
                table_name: Name of the table
                column_name: Name of the column to get unique values from
                schema_name: Optional schema name
                limit: Maximum number of unique values to return (default: 25)

            Returns:
                String representation of unique values in the column
            """
            # Validate inputs
            if not self._validate_identifier(table_name):
                return f"Error: Invalid table name '{table_name}'"

            if not self._validate_identifier(column_name):
                return f"Error: Invalid column name '{column_name}'"

            if schema_name and not self._validate_identifier(schema_name):
                return f"Error: Invalid schema name '{schema_name}'"

            # Validate and cap limit
            limit = self._validate_limit(limit)

            try:
                async with self.engine.connect() as conn:

                    def check_column(sync_conn):
                        inspector = inspect(sync_conn)
                        columns = inspector.get_columns(table_name, schema=schema_name)
                        column_names = [col["name"] for col in columns]
                        return column_names

                    column_names = await conn.run_sync(check_column)
                    table_ref = (
                        f"{schema_name}.{table_name}" if schema_name else table_name
                    )

                    if column_name not in column_names:
                        return f"Column '{column_name}' not found in table {table_ref}. Available columns: {', '.join(column_names)}"

                    # Build safe query using SQLAlchemy constructs
                    table_obj = table(table_name, schema=schema_name)
                    col_obj = column(column_name)
                    frequency_col = func.count(col_obj).label("frequency")

                    stmt = (
                        select(col_obj, frequency_col)
                        .select_from(table_obj)
                        .where(col_obj.isnot(None))
                        .group_by(col_obj)
                        .order_by(frequency_col.desc(), col_obj)
                        .limit(limit)
                    )

                    # Get the values and their frequencies
                    result = await conn.execute(stmt)
                    freq_data = [(str(row[0]), row[1]) for row in result.fetchall()]

                    if not freq_data:
                        return f"No values found in column '{column_name}' of table {table_ref}."

                    header = f"Unique values in {table_ref}.{column_name}"
                    if limit and len(freq_data) >= limit:
                        header += f" (limited to {limit} values)"

                    # Format the output with frequency counts
                    return f"{header}:\n\n" + "\n".join(
                        f"{val} (count: {count})" for val, count in freq_data
                    )
            except SQLAlchemyError as e:
                return f"Database error: {str(e)}"
            except Exception as e:
                return f"Error: {str(e)}"
