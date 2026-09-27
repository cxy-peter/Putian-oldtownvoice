"""Stateless ASGI deployment for Vercel; private corpora stay in browser IndexedDB.
No filesystem database, process-local login sessions, or credentials in static assets.
Run locally: uvicorn cloud_app:app --host 127.0.0.1 --port 8787
"""
import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import os
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from engine import MODELS, WARNING, Protocol, endpoints, translation_body, validate_corpus
from store import SEED

ROOT = Path(__file__).resolve().parent
COOKIE = "pv_cloud_session"
MAX_SECONDS = 240
HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; media-src 'self' blob:; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "Permissions-Policy": "microphone=(self), camera=(), geolocation=()"}


def origins(env):
    values = [v.strip() for v in env.get("ALLOWED_ORIGINS", "").split(",") if v.strip()]
    if env.get("PUBLIC_ORIGIN"):
        values.append(env["PUBLIC_ORIGIN"])
    for key in ("VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL"):
        if env.get(key):
            values.append("https://" + env[key])
    if not env.get("VERCEL"):
        values += ["http://localhost:8787", "http://127.0.0.1:8787"]
    result = set()
    for value in values:
        value = value.rstrip("/")
        u = urlsplit(value)
        local = u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1") and not env.get("VERCEL")
        if not u.hostname or u.username or u.password or u.path or u.query or u.fragment or "*" in value or (u.scheme != "https" and not local):
            raise ValueError("Allowed origins must be exact HTTPS origins, without paths or wildcards.")
        result.add(value)
    return result


def signing_key(env):
    access = env.get("APP_ACCESS_CODE", "")
    return hashlib.sha256(("putian-cloud-v1\0" + env.get("SESSION_SECRET", "") + "\0" + access).encode()).digest()


def make_token(key, now=None):
    expiry = int(time.time() if now is None else now) + 43200
    payload = f"{expiry}.{secrets.token_urlsafe(24)}"
    return payload + "." + hmac.new(key, payload.encode(), "sha256").hexdigest()


def valid_token(token, key, now=None):
    if not isinstance(token, str) or len(token) > 300:
        return False
    try:
        expiry, nonce, sig = token.split(".")
        now = int(time.time() if now is None else now)
        expected = hmac.new(key, f"{expiry}.{nonce}".encode(), "sha256").hexdigest()
        return now < int(expiry) <= now + 43200 and len(nonce) >= 20 and hmac.compare_digest(sig, expected)
    except (ValueError, TypeError):
        return False


def create_cloud_app(config=None):
    env = dict(os.environ) if config is None else dict(config)
    access = env.get("APP_ACCESS_CODE", "")
    if access and len(access) < 24:
        raise ValueError("Cloud APP_ACCESS_CODE requires at least 24 characters.")
    allowed, key = origins(env), signing_key(env)
    urls = endpoints(env.get("DASHSCOPE_WORKSPACE_ID", ""))
    # Best-effort instance limits, NOT a durable global spending cap.
    state = {"active": 0, "translations": 0, "day": "", "seconds": 0}
    rates = defaultdict(deque)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.env, app.state.allowed = env, allowed
    app.state.upstream_urls = urls  # Private test injection only; not an HTTP option.

    def authenticated(conn):
        return bool(access) and valid_token(conn.cookies.get(COOKIE, ""), key)

    def rate_ok(conn, kind, limit):
        now = time.monotonic()
        ip = conn.client.host if conn.client else "unknown"
        bucket = rates[(kind, ip)]
        while bucket and bucket[0] <= now - 60:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        if len(rates) > 2000:
            rates.clear()
        return True

    def reply(body, status=200):
        return JSONResponse(body, status_code=status, headers=HEADERS)

    async def body(request, limit=200000):
        raw = bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw) > limit:
                raise ValueError("请求超过大小限制。")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("请求必须为 JSON 对象。")
        return value

    @app.middleware("http")
    async def security(request: Request, call_next):
        path = request.url.path
        if request.method not in ("GET", "HEAD") and request.headers.get("origin") not in allowed:
            return reply({"error": "来源未获允许；请把实际域名加入 ALLOWED_ORIGINS。"}, 403)
        if path.startswith("/api/") and path not in ("/api/status", "/api/login") and not authenticated(request):
            return reply({"error": "请先连接应用访问码。"}, 401)
        if path.startswith("/api/") and not rate_ok(request, "api", 60):
            return reply({"error": "操作过于频繁，请稍后重试。"}, 429)
        try:
            response = await call_next(request)
        except (ValueError, TypeError, KeyError, UnicodeDecodeError):
            response = reply({"error": "输入无效，请检查字段与长度。"}, 400)
        except Exception:
            response = reply({"error": "服务异常；没有生成替代结果。"}, 500)
        response.headers.update(HEADERS)
        return response

    @app.get("/healthz")
    async def health():
        return {"ok": True, "runtime": "asgi-cloud", "version": "0.3"}

    @app.get("/api/status")
    async def status(request: Request):
        return {"keyConfigured": bool(env.get("DASHSCOPE_API_KEY")), "accessConfigured": bool(access),
            "authenticated": authenticated(request), "models": MODELS, "warning": WARNING,
            "liveVerified": False, "dialectValidated": False, "fineTuned": False,
            "maxSeconds": MAX_SECONDS, "storageMode": "browser", "seedCorpus": {**SEED, "revision": 1},
            "storageNotice": "云端版：词库和音频仅保存于当前浏览器，不会自动同步。换域名、清理浏览器或设备前请导出。",
            "quotaMode": "instance-best-effort"}

    @app.post("/api/login")
    async def login(request: Request):
        if not rate_ok(request, "login", 10):
            return reply({"error": "登录尝试过于频繁。"}, 429)
        code = (await body(request, 2000)).get("code", "")
        if not access or not isinstance(code, str) or len(code) > 200 or not hmac.compare_digest(hashlib.sha256(code.encode()).digest(), hashlib.sha256(access.encode()).digest()):
            return reply({"error": "访问码错误，或服务端尚未配置。"}, 401)
        result = reply({"ok": True})
        result.set_cookie(COOKIE, make_token(key), max_age=43200, httponly=True,
            secure=request.headers.get("origin", "").startswith("https://"), samesite="strict", path="/")
        return result

    @app.post("/api/logout")
    async def logout():
        result = reply({"ok": True})
        result.delete_cookie(COOKIE, path="/")
        return result

    @app.post("/api/validate-corpus")
    async def validate(request: Request):
        return validate_corpus(await body(request))

    @app.post("/api/translate")
    async def translate(request: Request):
        if not env.get("DASHSCOPE_API_KEY"):
            return reply({"error": "后端未配置百炼密钥。"}, 503)
        data = await body(request)
        payload = translation_body(data.get("text"), data.get("target"), validate_corpus(data.get("corpus", SEED)))
        if state["translations"] >= 2:
            return reply({"error": "已有翻译正在处理。"}, 429)
        state["translations"] += 1
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=40)) as http:
                async with http.post(app.state.upstream_urls[2], json=payload, headers={"Authorization": "Bearer " + env["DASHSCOPE_API_KEY"]}) as response:
                    if response.status != 200:
                        return reply({"error": f"翻译接口 HTTP {response.status}；请核对权限与额度。"}, 502)
                    raw = await response.content.read(200001)
                    if len(raw) > 200000:
                        return reply({"error": "翻译响应过大。"}, 502)
                    result = json.loads(raw)["choices"][0]["message"]["content"]
                    if not isinstance(result, str):
                        raise ValueError("Bad upstream format")
                    return {"text": result, "target": data["target"], "model": payload["model"], "source": data["text"]}
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return reply({"error": "百炼连接失败或超时，原文仍保留。"}, 502)
        finally:
            state["translations"] -= 1

    @app.websocket("/ws")
    async def stream(ws: WebSocket):
        if ws.headers.get("origin") not in allowed or not authenticated(ws) or not rate_ok(ws, "ws", 12):
            await ws.close(code=1008)
            return
        await ws.accept()
        if not env.get("DASHSCOPE_API_KEY") or state["active"] >= 2:
            await ws.send_json({"type": "error", "message": "密钥未配置，或当前实例识别任务已满。"})
            await ws.close(code=1013)
            return
        state["active"] += 1
        tasks = []
        async def emit(value):
            await ws.send_json(value)
        try:
            async with asyncio.timeout(275):
                raw = await asyncio.wait_for(ws.receive_text(), 10)
                if len(raw.encode()) > 200000:
                    raise ValueError("启动请求过大。")
                first = json.loads(raw)
                if not isinstance(first, dict) or first.get("type") != "start" or first.get("consent") is not True:
                    raise ValueError("录音前须明确同意云端识别。")
                corpus = validate_corpus(first.get("corpus", SEED))
                proto = Protocol(first.get("engine", "qwen31"), corpus, first.get("district", "莆田城区"), first.get("silence", 800), first.get("enhance", True))
                upstream_urls = app.state.upstream_urls
                endpoint = upstream_urls[1] + "?model=" + proto.model if proto.engine == "qwen3" else upstream_urls[0]
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=270, connect=15)) as http:
                    async with http.ws_connect(endpoint, headers={"Authorization": "Bearer " + env["DASHSCOPE_API_KEY"]}, heartbeat=20, max_msg_size=1048576) as upstream:
                        await upstream.send_json(proto.start())
                        async with asyncio.timeout(20):
                            while True:
                                message = await upstream.receive()
                                if message.type != aiohttp.WSMsgType.TEXT:
                                    raise ValueError("云端在任务开始前关闭连接。")
                                event = proto.event(json.loads(message.data))
                                if event and event["type"] == "error":
                                    await emit(event)
                                    return
                                if event and event["type"] == "ready":
                                    await emit({**event, "corpusRevision": first.get("corpusRevision", 0), "maxSeconds": MAX_SECONDS,
                                        "hotwordsApplied": proto.engine == "qwen31" and proto.enhance, "warning": WARNING})
                                    break
                        start = time.monotonic()
                        async def outbound():
                            sent = 0
                            while True:
                                msg = await ws.receive()
                                if msg["type"] == "websocket.disconnect":
                                    return False
                                pcm = msg.get("bytes")
                                if pcm is not None:
                                    if not 0 < len(pcm) <= 12800 or len(pcm) % 2:
                                        raise ValueError("PCM 音频帧无效。")
                                    sent += len(pcm)
                                    if sent > MAX_SECONDS * 32000 or sent > (time.monotonic() - start + 3) * 32000:
                                        raise ValueError("超过录音时长或发送速率上限。")
                                    day = time.strftime("%Y-%m-%d", time.gmtime())
                                    if state["day"] != day:
                                        state.update(day=day, seconds=0)
                                    if state["seconds"] + len(pcm) / 32000 > int(env.get("MAX_DAILY_AUDIO_SECONDS", "1800")):
                                        raise ValueError("当前实例已达音频预算。此限额不跨实例累计。")
                                    state["seconds"] += len(pcm) / 32000
                                    payload = proto.audio(pcm)
                                    if isinstance(payload, bytes):
                                        await upstream.send_bytes(payload)
                                    else:
                                        await upstream.send_json(payload)
                                else:
                                    raw = msg.get("text", "")
                                    if len(raw) > 1000:
                                        raise ValueError("控制消息过大。")
                                    if json.loads(raw).get("type") == "stop":
                                        await upstream.send_json(proto.finish())
                                        return True
                        async def inbound():
                            async for message in upstream:
                                if message.type != aiohttp.WSMsgType.TEXT:
                                    break
                                event = proto.event(json.loads(message.data))
                                if event:
                                    await emit(event)
                                    if event["type"] in ("done", "error"):
                                        return
                            await emit({"type": "error", "message": "云端提前断开，未完成片段仍是草稿。"})
                        sender, receiver = asyncio.create_task(outbound()), asyncio.create_task(inbound())
                        tasks = [sender, receiver]
                        finished, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                        if sender in finished:
                            if sender.result():
                                await asyncio.wait_for(receiver, 20)
                        else:
                            receiver.result()
        except WebSocketDisconnect:
            pass
        except (ValueError, KeyError, TypeError, aiohttp.ClientError, asyncio.TimeoutError):
            with contextlib.suppress(Exception):
                await emit({"type": "error", "message": "连接失败、超时或输入无效；请检查网络、模型权限与额度。原文已保留，没有替代结果。"})
        except Exception:
            with contextlib.suppress(Exception):
                await emit({"type": "error", "message": "识别异常，已停止发送。"})
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            state["active"] -= 1
            with contextlib.suppress(Exception):
                await ws.close()

    @app.get("/")
    async def home():
        return FileResponse(ROOT / "public" / "index.html")

    @app.get("/{asset}")
    async def static(asset: str):
        if asset not in ("app.js", "styles.css", "capture.js", "local-store.js"):
            return reply({"error": "Not found"}, 404)
        return FileResponse(ROOT / "public" / asset)
    return app


app = create_cloud_app()
