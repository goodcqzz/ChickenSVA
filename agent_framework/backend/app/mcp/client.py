"""
MCP (Model Context Protocol) 客户端

提供与MCP服务器的通信能力，支持：
- 工具发现与注册
- 工具调用代理
- SSE/HTTP传输
"""

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class MCPToolInfo:
    """MCP工具信息"""

    def __init__(self, name: str, description: str, input_schema: Dict[str, Any]):
        self.name = name
        self.description = description
        self.input_schema = input_schema

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


class MCPClient:
    """
    MCP服务器客户端

    通过HTTP/SSE与MCP服务器通信，发现和调用工具
    """

    def __init__(self, server_url: Optional[str] = None):
        self._server_url = (server_url or settings.mcp_server_url).rstrip("/")
        read_timeout = float(getattr(settings, "mcp_http_timeout_seconds", 300.0) or 300.0)
        self._client = httpx.AsyncClient(
            base_url=self._server_url,
            timeout=httpx.Timeout(read_timeout, connect=10.0),
        )
        self._tools: Dict[str, MCPToolInfo] = {}
        self._initialized = False

    @property
    def server_url(self) -> str:
        """返回MCP服务器URL"""
        return self._server_url

    @property
    def is_connected(self) -> bool:
        """返回连接状态"""
        return self._initialized and len(self._tools) > 0

    async def initialize(self) -> bool:
        """
        初始化MCP连接，发现可用工具

        Returns:
            是否初始化成功
        """
        try:
            tools = await self.discover_tools()
            if tools:
                self._initialized = True
                logger.info(f"MCP初始化成功，发现 {len(tools)} 个工具")
                return True
            else:
                logger.warning("MCP初始化：未发现工具")
                self._initialized = True
                return True
        except Exception as e:
            logger.warning(f"MCP初始化失败: {e}")
            return False

    async def discover_tools(self) -> List[MCPToolInfo]:
        """
        从MCP服务器发现可用工具

        Returns:
            工具信息列表
        """
        tools = []
        endpoints = [
            ("GET", "/mcp/v1/tools/list"),
            ("POST", "/mcp/v1/tools/list", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
            ("GET", "/tools"),
            ("GET", "/mcp/v1"),
        ]

        for method, path, *payload in endpoints:
            try:
                if method == "GET":
                    response = await self._client.get(path)
                else:
                    response = await self._client.post(path, json=payload[0])

                if response.status_code == 200:
                    data = response.json()
                    # 处理 /mcp/v1/tools/list 返回格式 {"result": {"tools": [...]}}
                    if "result" in data and isinstance(data["result"], dict):
                        data = data["result"]
                    tool_list = data if isinstance(data, list) else data.get("tools", [])

                    for tool_data in tool_list:
                        name = tool_data.get("name", "")
                        description = tool_data.get("description", "")
                        input_schema = tool_data.get("inputSchema", {})

                        if name:
                            tool_info = MCPToolInfo(
                                name=name,
                                description=description,
                                input_schema=input_schema,
                            )
                            tools.append(tool_info)
                            self._tools[name] = tool_info
                    if tools:
                        logger.info(f"MCP工具发现成功 via {path}: {len(tools)} 个工具")
                        break
                else:
                    logger.debug(f"MCP工具发现 {path} 返回状态码: {response.status_code}")
            except httpx.ConnectError:
                logger.debug(f"MCP服务器连接失败 {path}，跳过")
                break
            except Exception as e:
                logger.debug(f"MCP工具发现 {path} 异常: {e}")

        return tools

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        调用MCP工具

        与 mcp_http_server.py 对齐：POST /mcp/v1/tools/call，JSON-RPC 或扁平 name/arguments。
        """
        try:
            payload: Dict[str, Any] = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments or {}},
            }
            response = await self._client.post("/mcp/v1/tools/call", json=payload)

            if response.status_code != 200:
                return {
                    "error": f"MCP工具调用失败: HTTP {response.status_code}",
                    "detail": response.text[:800],
                }

            data = response.json()
            if isinstance(data, dict) and data.get("error"):
                err = data["error"]
                msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                return {"error": f"MCP返回错误: {msg}", "detail": err}

            result = data.get("result") if isinstance(data, dict) else None
            if result is None:
                return {"error": "MCP响应缺少 result 字段", "raw": data}

            if isinstance(result, dict):
                return result
            return {"result": result}
        except httpx.ConnectError:
            return {"error": "MCP服务器连接失败"}
        except Exception as e:
            return {"error": f"MCP工具调用异常: {str(e)}"}

    async def health_check(self) -> Dict[str, Any]:
        """
        检查MCP服务器健康状态

        Returns:
            健康状态信息
        """
        try:
            response = await self._client.get("/health", timeout=5.0)
            if response.status_code == 200:
                return {"status": "up", "url": self._server_url}
        except Exception:
            pass
        return {"status": "down", "url": self._server_url}

    def get_tool(self, name: str) -> Optional[MCPToolInfo]:
        """获取工具信息"""
        return self._tools.get(name)

    def get_all_tools(self) -> List[MCPToolInfo]:
        """获取所有已发现的工具"""
        return list(self._tools.values())

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    async def close(self):
        """关闭连接"""
        await self._client.aclose()
