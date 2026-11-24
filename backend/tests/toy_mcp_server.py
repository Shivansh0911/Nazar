"""TEST-ONLY MCP server (stdio): one read-only tool, one tool that would change something."""
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

app = MCPServer("toy")


@app.tool(annotations=ToolAnnotations(read_only_hint=True))
def echo(text: str) -> str:
    """Return the text."""
    return "echo:" + text


@app.tool()
def post_message(channel: str, text: str) -> str:
    """Post a message to a channel."""
    return f"posted to {channel}: {text}"


if __name__ == "__main__":
    app.run("stdio")
