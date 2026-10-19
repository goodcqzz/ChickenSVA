"""
MCP (Model Context Protocol) 模块

提供与MCP服务器的通信和工具桥接功能
"""

from app.mcp.client import MCPClient, MCPToolInfo
from app.mcp.bridge import MCPToolBridge

__all__ = ["MCPClient", "MCPToolInfo", "MCPToolBridge"]
