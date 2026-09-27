"""Explicit real API test, billable. Never runs during CI.
python scripts/live_check.py path/to/consented_16k_mono.wav qwen31
No key, audio or transcript is printed. Check request events locally to validate protocol.
"""
import asyncio
import json
import sys
import time
import wave
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os
import aiohttp
from app import load_env
from engine import Protocol, endpoints
from store import SEED

async def main():
    load_env()
    key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not key:
        raise ValueError("Missing DASHSCOPE_API_KEY")
    with wave.open(sys.argv[1]) as w:
        if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, 16000):
            raise ValueError("Use mono 16-bit 16kHz WAV")
        pcm = w.readframes(w.getnframes())
    if not 9600 <= len(pcm) <= 1920000:
        raise ValueError("Use a consented 0.3–60 second sample")
    p = Protocol(sys.argv[2] if len(sys.argv)>2 else "qwen31", SEED)
    a, b, _ = endpoints(os.environ.get("DASHSCOPE_WORKSPACE_ID", ""))
    url = b+"?model="+p.model if p.engine=="qwen3" else a
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=100,connect=15)) as http:
        async with http.ws_connect(url, headers={"Authorization":"Bearer "+key}) as ws:
            await ws.send_json(p.start())
            while True:
                e = p.event(await asyncio.wait_for(ws.receive_json(),20))
                if e and e["type"]=="error":
                    raise ValueError(e["code"])
                if e and e["type"]=="ready":
                    break
            async def send():
                for i in range(0,len(pcm),3200):
                    item=p.audio(pcm[i:i+3200])
                    if isinstance(item,bytes): await ws.send_bytes(item)
                    else: await ws.send_json(item)
                    await asyncio.sleep(.1)
                await ws.send_json(p.finish())
            task=asyncio.create_task(send()); finals=0; interim=0; completed=False
            try:
                async with asyncio.timeout(85):
                    async for msg in ws:
                        if msg.type!=aiohttp.WSMsgType.TEXT: break
                        e=p.event(json.loads(msg.data))
                        if not e: continue
                        if e["type"]=="segment":
                            finals+=int(e["final"]);interim+=int(not e["final"])
                        if e["type"]=="error": raise ValueError(e["code"])
                        if e["type"]=="done":
                            completed=True
                            print(json.dumps({"protocol_completed":True,"model":p.model,"final_segments":finals,"interim_events":interim,"putian_accuracy_validated":False}));break
                    if not completed: raise ValueError("Stream ended without done")
            finally:
                task.cancel();await asyncio.gather(task,return_exceptions=True)

if __name__=="__main__":
    try: asyncio.run(main())
    except Exception as e:
        print("Live check did not complete:",type(e).__name__)
        sys.exit(1)
