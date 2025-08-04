# SQLAlchemy MCP Server 🧙

A Model Context Protocol (MCP) server that enables AI assistants to interact with your databases safely and efficiently. Connect to SQLite, PostgreSQL, or MySQL databases and let AI help you explore schemas, query data, and analyze your database structure.

> This mcp-server is inspired by langchain's [SQLDatabase-toolkit](https://python.langchain.com/api_reference/community/agent_toolkits/langchain_community.agent_toolkits.sql.toolkit.SQLDatabaseToolkit.html) and makes use of Python's [SQLAlchemy](https://www.sqlalchemy.org/) library.

## What This Does

This MCP server allows AI assistants to:

- 🔍 **Explore your database structure** - List schemas, tables, columns, and relationships
- 📊 **Query your data safely** - Execute read-only queries with built-in safety controls
- 🛡️ **Protect your data** - Read-only mode prevents accidental data modification
- 📈 **Analyze relationships** - Understand how your tables connect through foreign keys
- 🔧 **Support multiple databases** - Works with SQLite, PostgreSQL, and MySQL

### Available Tools

The server provides 8 powerful tools for database interaction:

#### 🔍 **Schema Discovery Tools**

| Tool | Parameters | Description | Safety |
|------|------------|-------------|--------|
| **`list_schemas`** | _none_ | Lists all schemas in the database | ✅ Safe |
| **`list_tables`** | `schema` (optional) | Lists all tables, optionally filtered by schema | ✅ Safe |
| **`describe_table`** | `table_name`, `schema` (optional) | Shows table structure: columns, types, constraints, foreign keys | ✅ Safe |
| **`get_table_relationships`** | _none_ | Maps all foreign key relationships across the database | ✅ Safe |

#### 📊 **Data Exploration Tools**

| Tool | Parameters | Description | Safety |
|------|------------|-------------|--------|
| **`get_table_data`** | `table_name`, `schema` (optional), `limit` (default: 10) | Returns sample data from a table | ✅ Safe |
| **`get_unique_values`** | `table_name`, `column_name`, `schema` (optional), `limit` (default: 25) | Shows unique values in a column with frequency counts | ✅ Safe |

#### ⚡ **Query Execution Tools**

| Tool | Parameters | Description | Safety |
|------|------------|-------------|--------|
| **`execute_read_query`** | `sql` | Executes read-only SQL (SELECT, SHOW, DESCRIBE, EXPLAIN, WITH) | ✅ Safe |
| **`execute_query`** | `sql` | Executes any SQL including writes (INSERT, UPDATE, DELETE, DDL) | ⚠️ **Destructive** |

#### 🛡️ **Built-in Safety Features**

- **Automatic Input Validation**: All table/column names are validated against SQL injection
- **Result Limits**: Default maximum of 25 rows returned (configurable)
- **Query Timeout**: Automatic timeout after 30 seconds (configurable)
- **Read-Only Mode**: When enabled, blocks all write operations
- **Smart Query Detection**: Automatically categorizes queries as safe or destructive

## Quick Setup

### Option 1: Install via uvx (Recommended)

Add to your AI assistant's MCP configuration (see [detailed setup instructions](#add-to-your-ai-assistant)):

```json
{
  "mcpServers": {
    "sqlalchemy": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/woonstadrotterdam/mcp-sqlalchemy.git", "mcp-server"],
      "env": {
        "DATABASE_URL": "sqlite:////absolute/path/to/database.db"
      }
    }
  }
}
```

### Option 2: Local Development Setup

For development or customization:

```bash
# Clone the repository
git clone https://github.com/woonstadrotterdam/mcp-sqlalchemy.git
cd mcp-sqlalchemy

uv venv
source .venv/bin/activate # or .venv/Scripts/activate on Windows

# Install dependencies
uv sync
```

#### Test the Connection

```bash
# Start the development server to test using the proper entry point
uv run mcp dev mcp-server
```

This will open a web interface where you can test the connection and explore your database.

## Add to Your AI Assistant

### For uvx Installation (Recommended)

Add this to your AI assistant's MCP configuration file:

#### Claude Desktop (MacOS/Windows)

Edit your `claude_desktop_config.json` file:

```json
{
  "mcpServers": {
    "sqlalchemy": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/woonstadrotterdam/mcp-sqlalchemy.git",
        "mcp-server"
      ],
      "env": {
        "DATABASE_URL": "sqlite:////absolute/path/to/database.db",
        "READ_ONLY_MODE": "true"
      }
    }
  }
}
```

#### Other MCP-Compatible AI Assistants

Use the same configuration format above. The key fields are:

- **`command`**: `"uvx"` for installation from Git
- **`args`**: `["--from", "git+<your-repo-url>", "mcp-server"]`
- **`env.DATABASE_URL`**: Your database connection string
- **`env.READ_ONLY_MODE`**: `"true"` for safety (recommended)

See [Database Connection Examples](#database-connection-examples) for specific database URL formats.

### For Local Development Setup

If you're developing locally, use this configuration instead:

```json
{
  "mcpServers": {
    "sqlalchemy": {
      "command": "uv",
      "args": ["run", "mcp-server"],
      "cwd": "/absolute/path/to/mcp-sqlalchemy",
      "env": {
        "DATABASE_URL": "sqlite:////absolute/path/to/database.db",
        "READ_ONLY_MODE": "true"
      }
    }
  }
}
```

### Installation Method Comparison

| Method | Pros | Cons | Best For |
|--------|------|------|----------|
| **uvx** | Simple install, automatic updates, works anywhere | Requires internet | Most users |
| **Local** | Works offline, can modify code, full control | Manual updates, manage dependencies | Developers |

### Updating Your Installation

**For uvx installations:**

```bash
# Updates happen automatically when you restart your AI assistant
# Or force update with:
uvx --force --from git+https://github.com/woonstadrotterdam/mcp-sqlalchemy.git mcp-server
```

**For local installations:**

```bash
cd mcp-sqlalchemy
git pull
uv sync
```

## Database Connection Examples

### SQLite (File-based)

```bash
# Local database file
DATABASE_URL="sqlite:///database/myapp.db"

# Relative path
DATABASE_URL="sqlite:///./data/database.db"

# Absolute path
DATABASE_URL="sqlite:////full/path/to/database.db"
```

### PostgreSQL

```bash
# Basic connection
DATABASE_URL="postgresql://user:password@localhost:5432/dbname"

# With specific schema
DATABASE_URL="postgresql://user:password@localhost:5432/dbname"
DB_SCHEMA_NAME="public"

# Remote database
DATABASE_URL="postgresql://user:password@db.example.com:5432/dbname"
```

### MySQL

```bash
# Local MySQL
DATABASE_URL="mysql://user:password@localhost:3306/dbname"

# Remote MySQL
DATABASE_URL="mysql://user:password@mysql.example.com:3306/dbname"
```

## Safety Features

### Read-Only Mode (Recommended)

Enable read-only mode to prevent any data modifications:

```python
# The server automatically detects and blocks:
# - INSERT, UPDATE, DELETE statements
# - DROP, CREATE, ALTER statements
# - Any potentially destructive operations
```

### Automatic Protections

- **Query Validation**: Blocks dangerous SQL patterns
- **Result Limits**: Prevents overwhelming responses (default: 25 rows)
- **Read-Only by Default**: Safe mode enabled by default
- **Timeout Protection**: Queries timeout after 30 seconds
- **Input Sanitization**: Validates table and column names

## What Your AI Can Do

### Database Exploration

- **"Show me all the tables in my database"** → Lists all tables across schemas
- **"Describe the users table"** → Shows columns, types, and constraints
- **"What tables are related to the orders table?"** → Shows foreign key relationships
- **"List all schemas in the database"** → Shows available schemas

### Data Analysis

- **"Show me a sample of the users table"** → Returns first 10 rows
- **"What are the unique values in the status column?"** → Lists distinct values with counts
- **"Query all active users"** → Executes: `SELECT * FROM users WHERE status = 'active'`
- **"How many orders were placed last month?"** → Custom date-based queries

### Schema Understanding

- **"Explain the database structure"** → Comprehensive schema overview
- **"How are customers connected to orders?"** → Relationship mapping
- **"What indexes exist on the products table?"** → Index information

## Configuration Options

You can customize the server behavior:

```bash
# Set maximum rows returned per query
MAX_RESULT_ROWS=50

# Set query timeout (seconds)
MAX_QUERY_TIMEOUT=60

# Enable read-only mode
READ_ONLY_MODE=true

# Set default schema (PostgreSQL)
DB_SCHEMA_NAME=public
```

## Troubleshooting

### Installation Issues

#### "uvx: command not found"

- Install uvx: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Or via pip: `pip install uv` then use `uv tool run` instead of `uvx`

#### "Repository not accessible" (uvx installation)

- Make sure the repository URL is correct and public
- For private repos, use SSH: `git+ssh://git@github.com/woonstadrotterdam/mcp-sqlalchemy.git`

### Connection Issues

#### "Database URL must be provided"

- Make sure `DATABASE_URL` is set in your MCP configuration's `env` section or add `--database-url` to the command line
- Check the URL format matches your database type

#### "No module named 'greenlet'"

- For local installs: Run `uv sync` to install all dependencies
- For uvx installs: This should auto-install; try forcing reinstall with `uvx --force ...`
- The `greenlet` package is required for async database operations

#### "Connection refused"

- Verify your database server is running
- Check the hostname, port, username, and password
- For PostgreSQL/MySQL, ensure the database exists

### Query Issues

#### "Query timeout"

- The query is taking too long (>30 seconds)
- Add `LIMIT` clauses to large queries
- Consider adding database indexes for better performance

#### "Only read-only queries allowed"

- You're in read-only mode (this is good for safety!)
- Use the "Execute Read Query" tool instead
- Or disable read-only mode if you need write access

## Need Help?

1. **Test your connection** first:
   - For uvx installs: Run `uvx --from git+https://github.com/woonstadrotterdam/mcp-sqlalchemy.git mcp-server --http` and visit <http://localhost:8000>
   - For local installs: Run `uv run mcp dev mcp-server`
2. **Check the web interface** that opens to verify everything works
3. **Start with simple queries** like "list tables" before complex operations
4. **Use read-only mode** until you're comfortable with the setup

This server is designed to be safe by default - it will protect your data while giving your AI assistant powerful database exploration capabilities.
