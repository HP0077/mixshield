"""Tiny MCP server for the proxy tests: one tool whose name no rule knows ("wire_funds") and one read-only tool."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("wire-test", log_level="WARNING")
WIRED = []


@mcp.tool()
def wire_funds(account: str, amount: float, memo: str = "") -> dict:
    """Move money to an account."""
    WIRED.append(account)
    return {"status": "wired", "account": account, "count": len(WIRED)}


@mcp.tool()
def get_status() -> str:
    """Read-only."""
    return "ok"


if __name__ == "__main__":
    mcp.run()
