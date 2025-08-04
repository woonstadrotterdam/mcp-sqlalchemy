#!/bin/bash
# Setup script for pre-commit hooks

echo "🔧 Setting up pre-commit hooks for mcp-sqlalchemy..."

# Check if pre-commit is installed
if ! command -v pre-commit &> /dev/null; then
    echo "📦 Installing pre-commit..."
    uv add --dev pre-commit
else
    echo "✅ pre-commit is already installed"
fi

# Install the pre-commit hooks
echo "🔗 Installing pre-commit hooks..."
pre-commit install

echo "✅ Pre-commit hooks installed successfully!"
echo ""
echo "📋 Available hooks:"
echo "  - uv-lock: Ensures uv.lock is up to date"
echo "  - ruff: Linting and formatting"
echo "  - Various file checks (YAML, whitespace, etc.)"
echo ""
echo "🚀 Run 'pre-commit run --all-files' to check all files"
echo "💡 Hooks will run automatically on git commit"
