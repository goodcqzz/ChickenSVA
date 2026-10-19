#!/usr/bin/env python3
"""ChickenSV 临时反代（无 sudo）：静态 dist + /api、/ws 转发到后端 9801。

用法:
  python deploy/bin/serve-proxy.py
  # 浏览器: http://<服务器IP>:9800/
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

ROOT = Path(
    os.environ.get("CHICKENSV_ROOT")
    or str(Path(__file__).resolve().parents[2])
)
DIST = ROOT / "agent_framework/frontend/dist"
BACKEND = os.environ.get("CHICKENSV_BACKEND", "http://127.0.0.1:9801")
HOST = os.environ.get("CHICKENSV_PROXY_HOST", "0.0.0.0")
PORT = int(os.environ.get("CHICKENSV_PROXY_PORT", "9800"))

app = FastAPI(title="ChickenSV proxy", docs_url=None, redoc_url=None)
client = httpx.AsyncClient(base_url=BACKEND, timeout=600.0)

app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_api(path: str, request: Request) -> Response:
    url = f"/api/{path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"
    body = await request.body()
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in {"host", "content-length", "connection", "x-real-ip"}
    }
    # 追加本代理看到的对端地址到 X-Forwarded-For（与 Nginx $proxy_add_x_forwarded_for
    # 行为一致），让后端可按可信代理跳数解析真实客户端 IP，抵抗 XFF 伪造。
    client_host = request.client.host if request.client else ""
    incoming_xff = request.headers.get("x-forwarded-for")
    xff = f"{incoming_xff}, {client_host}" if incoming_xff else client_host
    if xff:
        headers["x-forwarded-for"] = xff
    if client_host:
        headers["x-real-ip"] = client_host
    headers["x-forwarded-proto"] = request.url.scheme
    upstream = await client.request(
        request.method,
        url,
        content=body or None,
        headers=headers,
    )
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers={
            k: v
            for k, v in upstream.headers.items()
            if k.lower() not in {"content-encoding", "transfer-encoding", "connection"}
        },
        media_type=upstream.headers.get("content-type"),
    )


@app.websocket("/ws/{path:path}")
async def proxy_ws(websocket: WebSocket, path: str) -> None:
    import websockets

    backend_ws = BACKEND.replace("http://", "ws://").replace("https://", "wss://")
    target = f"{backend_ws}/ws/{path}"
    if websocket.url.query:
        target = f"{target}?{websocket.url.query}"

    # 透传真实客户端 IP（追加本代理看到的对端地址到 X-Forwarded-For）
    client_host = websocket.client.host if websocket.client else ""
    incoming_xff = websocket.headers.get("x-forwarded-for")
    xff = f"{incoming_xff}, {client_host}" if incoming_xff else client_host
    fwd_headers = {}
    if xff:
        fwd_headers["X-Forwarded-For"] = xff
    if client_host:
        fwd_headers["X-Real-IP"] = client_host

    await websocket.accept()
    try:
        connect_cm = websockets.connect(target, additional_headers=fwd_headers)
    except TypeError:
        # 兼容旧版 websockets（extra_headers）
        connect_cm = websockets.connect(target, extra_headers=fwd_headers)
    async with connect_cm as upstream:
        import asyncio

        async def client_to_upstream() -> None:
            try:
                while True:
                    msg = await websocket.receive()
                    if msg["type"] == "websocket.disconnect":
                        break
                    if "text" in msg:
                        await upstream.send(msg["text"])
                    elif "bytes" in msg:
                        await upstream.send(msg["bytes"])
            except Exception:
                pass

        async def upstream_to_client() -> None:
            try:
                async for message in upstream:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)
            except Exception:
                pass

        await asyncio.gather(client_to_upstream(), upstream_to_client())


@app.get("/{full_path:path}")
async def spa(full_path: str) -> FileResponse:
    candidate = DIST / full_path
    if full_path and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(DIST / "index.html")


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
