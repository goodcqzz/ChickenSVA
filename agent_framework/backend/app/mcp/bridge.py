"""
MCP工具桥接器

将MCP服务器上的工具桥接到Agent工具注册中心，
使Agent可以透明地调用MCP工具
"""

import logging
from typing import Any, Dict, List, Optional

from app.agent.tool_registry import ToolRegistry, ToolParameter
from app.mcp.client import MCPClient

logger = logging.getLogger(__name__)


class MCPToolBridge:
    """
    MCP工具桥接器

    将MCP服务器发现的工具注册到Agent工具注册中心
    """

    def __init__(self, mcp_client: MCPClient, tool_registry: ToolRegistry):
        self._mcp_client = mcp_client
        self._tool_registry = tool_registry
        self._bridged_tools: List[str] = []

    async def bridge_all_tools(self) -> int:
        """
        将所有MCP工具桥接到工具注册中心

        Returns:
            成功桥接的工具数量
        """
        if not self._mcp_client.is_initialized:
            await self._mcp_client.initialize()

        mcp_tools = self._mcp_client.get_all_tools()
        bridged = 0

        for mcp_tool in mcp_tools:
            try:
                if self._tool_registry.has_tool(mcp_tool.name):
                    logger.debug(f"工具已存在，跳过: {mcp_tool.name}")
                    continue

                parameters = self._parse_parameters(mcp_tool.input_schema)

                async def make_handler(tool_name: str):
                    async def handler(**kwargs: Any) -> Dict[str, Any]:
                        return await self._mcp_client.call_tool(tool_name, kwargs)
                    return handler

                handler = await make_handler(mcp_tool.name)

                self._tool_registry.register(
                    name=mcp_tool.name,
                    description=mcp_tool.description,
                    parameters=parameters,
                    handler=handler,
                    category="mcp",
                )
                self._bridged_tools.append(mcp_tool.name)
                bridged += 1
                logger.info(f"桥接MCP工具: {mcp_tool.name}")

            except Exception as e:
                logger.error(f"桥接MCP工具失败 [{mcp_tool.name}]: {e}")

        return bridged

    def _parse_parameters(self, input_schema: Dict[str, Any]) -> List[ToolParameter]:
        """
        将MCP工具的JSON Schema参数转换为ToolParameter列表

        Args:
            input_schema: JSON Schema格式的参数定义

        Returns:
            ToolParameter列表
        """
        parameters = []
        properties = input_schema.get("properties", {})
        required = input_schema.get("required", [])

        for name, prop in properties.items():
            param_type = self._map_json_type(prop.get("type", "string"))
            description = prop.get("description", "")
            is_required = name in required
            default = prop.get("default")
            enum_values = prop.get("enum")

            parameters.append(
                ToolParameter(
                    name=name,
                    type=param_type,
                    description=description,
                    required=is_required,
                    default=default,
                    enum=enum_values,
                )
            )

        return parameters

    @staticmethod
    def _map_json_type(json_type: str) -> str:
        """将JSON Schema类型映射为工具参数类型"""
        type_map = {
            "string": "string",
            "number": "number",
            "integer": "integer",
            "boolean": "boolean",
            "array": "array",
            "object": "object",
        }
        return type_map.get(json_type, "string")

    @property
    def bridged_tools(self) -> List[str]:
        """已桥接的工具列表"""
        return self._bridged_tools.copy()

    @property
    def bridge_count(self) -> int:
        """已桥接的工具数量"""
        return len(self._bridged_tools)
