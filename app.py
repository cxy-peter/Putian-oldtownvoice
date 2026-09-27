"""莆田老城声: authenticated HTTP + true duplex WebSocket streaming.
Run one process with persistent DATA_DIR. No transcripts/audio are logged.
"""
import asyncio
import contextlib
import hashlib
import json
import os
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
from aiohttp import web
from engine import MODELS, WARNING, Protocol, endpoints, translation_body
from store import Store

ROOT = Path(__file__).resolve().parent
PUBLIC = {"/": "index.html", "/app.js": "app.js", "/styles.css": "styles.css", "/capture.js": "capture.js"}

def load_env(path=ROOT / ".env"):
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

def allowed_origin(request):
    origin = request.headers.get("Origin", "")
    configured = request.app["origin"]
    if configured:
        return origin == configured
    # Local development only. PUBLIC_ORIGIN is mandatory for remote sites.
    return origin in {"http://localhost:" + str(request.app["port"]), "http://127.0.0.1:" + str(request.app["port"])}

def authenticated(request):
    token = request.cookies.get("pv_session", "")
    expiry = request.app["sessions"].get(token, 0)
    return expiry > time.monotonic()

@web.middleware
async def security(request, handler):
    try:
        private = request.path.startswith("/api/") or request.path == "/ws"
        if (request.method not in ("GET", "HEAD") or request.path == "/ws") and not allowed_origin(request):
            raise web.HTTPForbidden(reason="来源未获允许；公网部署须设置 PUBLIC_ORIGIN。")
        if private and request.path not in ("/api/status", "/api/login") and not authenticated(request):
            raise web.HTTPUnauthorized(reason="请先输入应用访问码。")
        if private:
            now = time.monotonic()
            ip = request.remote or "unknown"
            bucket = request.app["rate"][ip]
            while bucket and bucket[0] < now - 60:
                bucket.popleft()
            if len(bucket) >= 60:
                raise web.HTTPTooManyRequests(reason="操作过于频繁，请稍后重试。")
            bucket.append(now)
            if len(request.app["rate"]) > 2000:
                request.app["rate"].clear()
        response = await handler(request)
    except web.HTTPException as e:
        response = web.json_response({"error": e.reason}, status=e.status)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        response = web.json_response({"error": "输入无效，请检查格式、授权勾选或字段长度。"}, status=400)
    except Exception:
        # Never dump exception payloads, API keys, audio, or translation input.
        response = web.json_response({"error": "服务请求失败；原始结果仍保留。"}, status=500)
    if not response.prepared:
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; media-src 'self' blob:; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            "Permissions-Policy": "microphone=(self), camera=(), geolocation=()"})
    return response

async def status(request):
    return web.json_response({"keyConfigured": bool(request.app["key"]), "accessConfigured": bool(request.app["access"]),
        "authenticated": authenticated(request), "models": MODELS, "warning": WARNING,
        "liveVerified": False, "dialectValidated": False, "fineTuned": False, "maxSeconds": 300})

async def login(request):
    code = (await request.json()).get("code", "")
    expected = request.app["access"]
    if not expected or not isinstance(code, str) or len(code) > 200 or not secrets.compare_digest(hashlib.sha256(code.encode()).digest(), hashlib.sha256(expected.encode()).digest()):
        raise web.HTTPUnauthorized(reason="访问码不正确，或后端尚未配置 APP_ACCESS_CODE。")
    now = time.monotonic()
    sessions = request.app["sessions"]
    for token in [t for t, expiry in sessions.items() if expiry < now]:
        del sessions[token]
    if len(sessions) >= 100:
        raise web.HTTPTooManyRequests(reason="会话数量已达上限。")
    token = secrets.token_urlsafe(32)
    sessions[token] = now + 43200
    response = web.json_response({"ok": True})
    response.set_cookie("pv_session", token, httponly=True, secure=request.app["origin"].startswith("https://"), samesite="Strict", max_age=43200, path="/")
    return response

async def logout(request):
    request.app["sessions"].pop(request.cookies.get("pv_session", ""), None)
    response = web.json_response({"ok": True})
    response.del_cookie("pv_session")
    return response

async def corpus(request):
    store = request.app["store"]
    if request.method == "PUT":
        try:
            value = store.save_corpus(await request.json())
        except ValueError as e:
            raise web.HTTPBadRequest(reason=str(e))
    else:
        value = store.corpus()
    return web.json_response(value)

async def samples(request):
    store = request.app["store"]
    if request.method == "POST":
        try:
            value = store.add_sample(await request.json())
        except ValueError as e:
            raise web.HTTPBadRequest(reason=str(e))
        return web.json_response(value, status=201)
    if request.method == "DELETE":
        store.remove_sample(request.match_info["id"])
        return web.json_response({"ok": True})
    return web.json_response(store.samples())

async def export(request):
    return web.Response(body=request.app["store"].export(), content_type="application/zip",
                        headers={"Content-Disposition": 'attachment; filename="putian-private-corpus.zip"'})

async def translate(request):
    if not request.app["key"]:
        raise web.HTTPServiceUnavailable(reason="后端未配置百炼密钥。")
    data = await request.json()
    body = translation_body(data.get("text"), data.get("target"), request.app["store"].corpus())
    if request.app["translations"] >= 2:
        raise web.HTTPTooManyRequests(reason="已有翻译正在处理。")
    request.app["translations"] += 1
    try:
        async with request.app["http"].post(request.app["endpoints"][2], json=body,
                headers={"Authorization": "Bearer " + request.app["key"]}, timeout=aiohttp.ClientTimeout(total=40)) as res:
            if res.status != 200:
                raise web.HTTPBadGateway(reason=f"翻译接口返回 HTTP {res.status}；请核对额度或模型权限。")
            if res.content_length and res.content_length > 200000:
                raise web.HTTPBadGateway(reason="翻译响应异常。")
            raw = await res.content.read(200001)
            if len(raw) > 200000:
                raise web.HTTPBadGateway(reason="翻译响应过大。")
            out = json.loads(raw)
            result = out["choices"][0]["message"]["content"]
            if not isinstance(result, str):
                raise web.HTTPBadGateway(reason="翻译格式与预期不符。")
            return web.json_response({"text": result, "model": body["model"], "target": data["target"], "source": data["text"]})
    except (aiohttp.ClientError, asyncio.TimeoutError):
        raise web.HTTPBadGateway(reason="翻译网络连接失败或超时；没有改写原始转写。")
    finally:
        request.app["translations"] -= 1

async def streaming(request):
    app = request.app
    if not app["key"]:
        raise web.HTTPServiceUnavailable(reason="后端未配置百炼密钥。")
    if app["active"] >= 2:
        raise web.HTTPTooManyRequests(reason="最多同时进行两个录音任务。")
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=16384)
    await ws.prepare(request)
    app["active"] += 1
    app["sockets"].add(ws)
    tasks = []
    async def emit(data):
        if not ws.closed:
            await ws.send_json(data)
    try:
        first = await asyncio.wait_for(ws.receive_json(), 10)
        if first.get("type") != "start" or first.get("consent") is not True:
            raise ValueError("启动前须明确同意向百炼发送音频。")
        proto = Protocol(first.get("engine", "qwen31"), app["store"].corpus(), first.get("district", "莆田城区"), first.get("silence", 800), first.get("enhance", True))
        base = app["endpoints"][1] + "?model=" + proto.model if proto.engine == "qwen3" else app["endpoints"][0]
        # TLS verification remains enabled; key only goes to the fixed official endpoint.
        async with app["http"].ws_connect(base, headers={"Authorization": "Bearer " + app["key"]}, heartbeat=20, max_msg_size=1024*1024) as upstream:
            await upstream.send_json(proto.start())
            async with asyncio.timeout(20):
                while True:
                    msg = await upstream.receive()
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        raise ValueError("百炼在任务开始前关闭连接。")
                    event = proto.event(json.loads(msg.data))
                    if event and event["type"] == "error":
                        await emit(event)
                        return ws
                    if event and event["type"] == "ready":
                        await emit({**event, "warning": WARNING, "corpusRevision": app["store"].corpus()["revision"], "hotwordsApplied": proto.engine == "qwen31" and proto.enhance})
                        break
            start = time.monotonic()
            async def outbound():
                sent = 0
                async with asyncio.timeout(310):
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.BINARY:
                            pcm = msg.data
                            if not 0 < len(pcm) <= 12800 or len(pcm) % 2:
                                raise ValueError("PCM 帧无效。")
                            sent += len(pcm)
                            if sent > 300*32000 or sent > (time.monotonic()-start+3)*32000:
                                raise ValueError("音频超过时长或发送速率限制。")
                            app["store"].reserve(len(pcm)/32000, app["daily_limit"])
                            payload = proto.audio(pcm)
                            if isinstance(payload, bytes):
                                await upstream.send_bytes(payload)
                            else:
                                await upstream.send_json(payload)
                        elif msg.type == aiohttp.WSMsgType.TEXT and json.loads(msg.data).get("type") == "stop":
                            await upstream.send_json(proto.finish())
                            return True
                    return False
            async def inbound():
                async for msg in upstream:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        break
                    event = proto.event(json.loads(msg.data))
                    if event:
                        if event["type"] == "segment":
                            event["elapsed_ms"] = round((time.monotonic()-start)*1000)
                        await emit(event)
                        if event["type"] in ("done", "error"):
                            return
                await emit({"type": "error", "message": "云端连接提前结束，未完成的片段仍标为草稿。"})
            sender, receiver = asyncio.create_task(outbound()), asyncio.create_task(inbound())
            tasks = [sender, receiver]
            finished, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if sender in finished:
                stopped = sender.result()
                if stopped:
                    await asyncio.wait_for(receiver, 20)
            else:
                receiver.result()
    except ValueError as e:
        await emit({"type": "error", "message": str(e)[:220]})
    except (aiohttp.ClientError, asyncio.TimeoutError):
        await emit({"type": "error", "message": "百炼连接失败或超时。检查网络、模型权限、北京地域 API Key 与余额；未产生替代结果。"})
    except Exception:
        await emit({"type": "error", "message": "实时识别异常，已停止发送。现有文字不会清除。"})
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        app["active"] -= 1
        app["sockets"].discard(ws)
        await ws.close()
    return ws

async def static(request):
    return web.FileResponse(ROOT / "public" / PUBLIC[request.path])

async def health(request):
    return web.json_response({"ok": True})

async def lifecycle(app):
    app["http"] = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=360, connect=15))
    yield
    for ws in list(app["sockets"]):
        await ws.close(code=1001, message=b"Server stopping")
    await app["http"].close()
    app["store"].close()

def create_app(config=None):
    env = dict(os.environ) if config is None else config
    access = env.get("APP_ACCESS_CODE", "")
    if access and len(access) < 16:
        raise ValueError("APP_ACCESS_CODE 至少 16 个字符。")
    origin = env.get("PUBLIC_ORIGIN", "").rstrip("/")
    if origin:
        u = urlsplit(origin)
        if u.scheme != "https" or not u.hostname or u.path or u.query or u.fragment or u.username:
            raise ValueError("PUBLIC_ORIGIN 应为 https://你的域名，不含路径。")
    app = web.Application(middlewares=[security], client_max_size=2800000)
    app.update({"key": env.get("DASHSCOPE_API_KEY", ""), "access": access, "origin": origin,
                "port": int(env.get("PORT", "8787")), "sessions": {}, "rate": defaultdict(deque),
                "active": 0, "translations": 0, "sockets": set(), "daily_limit": int(env.get("MAX_DAILY_AUDIO_SECONDS", "1800")),
                "store": Store(env.get("DATA_DIR", str(ROOT / "data"))), "endpoints": endpoints(env.get("DASHSCOPE_WORKSPACE_ID", ""))})
    app.cleanup_ctx.append(lifecycle)
    app.router.add_get("/healthz", health)
    app.router.add_get("/api/status", status)
    app.router.add_post("/api/login", login)
    app.router.add_post("/api/logout", logout)
    app.router.add_get("/api/corpus", corpus)
    app.router.add_put("/api/corpus", corpus)
    app.router.add_get("/api/samples", samples)
    app.router.add_post("/api/samples", samples)
    app.router.add_delete("/api/samples/{id}", samples)
    app.router.add_get("/api/export", export)
    app.router.add_post("/api/translate", translate)
    app.router.add_get("/ws", streaming)
    for route in PUBLIC:
        app.router.add_get(route, static)
    return app

if __name__ == "__main__":
    load_env()
    web.run_app(create_app(), host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8787")), access_log=None)
