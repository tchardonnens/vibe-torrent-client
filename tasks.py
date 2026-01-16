"""Invoke tasks for the torrent client project."""

from invoke import Context, task

SOURCES = "src/ tests/"


@task
def lint(ctx: Context) -> None:
    """Run ruff linter."""
    ctx.run(f"uv run ruff check {SOURCES}", pty=True)


@task
def format(ctx: Context, check: bool = False, fix: bool = False) -> None:
    """Run ruff formatter and optionally fix linting issues."""
    if fix:
        ctx.run(f"uv run ruff check --fix --unsafe-fixes {SOURCES}", pty=True)
        ctx.run(f"uv run ruff format {SOURCES}", pty=True)
    else:
        check_flag = "--check" if check else ""
        ctx.run(f"uv run ruff format {check_flag} {SOURCES}", pty=True)


@task
def test(ctx: Context, verbose: bool = True) -> None:
    """Run tests with pytest."""
    verbose_flag = "-v" if verbose else ""
    ctx.run(f"uv run pytest tests/ {verbose_flag}", pty=True)


@task
def check(ctx: Context) -> None:
    """Run all checks (lint, format check, tests)."""
    lint(ctx)
    format(ctx, check=True, fix=False)
    test(ctx)


@task
def mcp(ctx: Context, port: int = 8000) -> None:
    """Run the FastMCP server with HTTP transport."""
    ctx.run(f"cd src && uv run fastmcp run mcp_server/server.py --transport streamable-http --port {port}", pty=True)
