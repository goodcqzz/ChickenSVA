"""
MCP管理API

提供MCP服务器状态查询和工具管理接口
"""

import logging
from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/status")
async def mcp_status():
    """获取MCP服务器状态"""
    from app.main import mcp_client
    health = await mcp_client.health_check()
    return {
        "connected": health.get("status") == "up",
        "server_url": health.get("url", ""),
        "tools_discovered": mcp_client.tool_count,
        "initialized": mcp_client.is_initialized,
    }


@router.get("/tools")
async def mcp_tools():
    """获取MCP发现的工具列表"""
    from app.main import mcp_client
    tools = mcp_client.get_all_tools()
    return {
        "count": len(tools),
        "tools": [t.to_dict() for t in tools],
    }


@router.post("/refresh")
async def mcp_refresh():
    """重新发现MCP工具并桥接"""
    from app.main import mcp_client, mcp_bridge
    await mcp_client.initialize()
    bridged = await mcp_bridge.bridge_all_tools()
    return {
        "success": True,
        "bridged_count": bridged,
        "total_mcp_tools": mcp_client.tool_count,
    }
