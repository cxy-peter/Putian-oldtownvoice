"""Single-instance SQLite persistence. Audio and corpus are private, never static assets."""
import base64
import hashlib
import io
import json
import sqlite3
import time
import uuid
import wave
import zipfile
from pathlib import Path
from engine import text, validate_corpus

SEED = {"terms": [{"text": t, "weight": 3, "meaning": ""} for t in ["莆田", "仙游", "莆仙话", "妈祖", "湄洲岛", "兴化", "卤面"]], "examples": []}

def inspect_wav(raw):
    if not 44 < len(raw) <= 1920100:
        raise ValueError("语料音频最多 60 秒。")
    try:
        with wave.open(io.BytesIO(raw)) as w:
            if (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getcomptype()) != (1, 2, 16000, "NONE"):
                raise ValueError("请使用 16kHz 单声道 PCM16 WAV。")
            n = w.getnframes()
            if not 4800 <= n <= 960000 or len(w.readframes(n)) != n * 2:
                raise ValueError("音频长度无效或数据不完整。")
            return n / 16000
    except (wave.Error, EOFError) as e:
        raise ValueError("WAV 音频格式错误。") from e

class Store:
    def __init__(self, directory):
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(Path(directory) / "private.sqlite3"))
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("CREATE TABLE IF NOT EXISTS corpus (id INTEGER PRIMARY KEY, revision INTEGER, data TEXT); CREATE TABLE IF NOT EXISTS samples (id TEXT PRIMARY KEY, speaker TEXT, split TEXT, meta TEXT, audio BLOB); CREATE TABLE IF NOT EXISTS budget (day TEXT PRIMARY KEY, seconds REAL);")
        self.db.execute("INSERT OR IGNORE INTO corpus VALUES (1,1,?)", (json.dumps(SEED, ensure_ascii=False),))
        self.db.commit()
    def corpus(self):
        revision, raw = self.db.execute("SELECT revision,data FROM corpus WHERE id=1").fetchone()
        return {**json.loads(raw), "revision": revision}
    def save_corpus(self, obj):
        clean = validate_corpus(obj)
        with self.db:
            cur = self.db.execute("UPDATE corpus SET revision=revision+1,data=? WHERE id=1 AND revision=?", (json.dumps(clean, ensure_ascii=False), obj.get("revision", -1)))
            if cur.rowcount != 1:
                raise ValueError("词库已被其他页面修改，请重新加载后合并。")
        return self.corpus()
    def reserve(self, seconds, limit):
        day = time.strftime("%Y-%m-%d", time.gmtime())
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO budget VALUES (?,0)", (day,))
            current = self.db.execute("SELECT seconds FROM budget WHERE day=?", (day,)).fetchone()[0]
            if current + seconds > limit:
                raise ValueError("今日音频配额已用完。此限制按发送时长估算，不等于云账单。")
            self.db.execute("UPDATE budget SET seconds=seconds+? WHERE day=?", (seconds, day))
    def samples(self):
        return [json.loads(r[0]) for r in self.db.execute("SELECT meta FROM samples ORDER BY rowid DESC")]
    def add_sample(self, obj):
        if obj.get("consent") is not True or obj.get("reviewed") is not True:
            raise ValueError("保存前须获得录音授权并由母语者核对标注。")
        if self.db.execute("SELECT COUNT(*) FROM samples").fetchone()[0] >= 100:
            raise ValueError("MVP 最多保存 100 条语料，请导出整理后再添加。")
        try:
            raw = base64.b64decode(obj.get("audio", ""), validate=True)
        except (ValueError, TypeError) as e:
            raise ValueError("音频编码错误。") from e
        seconds = inspect_wav(raw)
        speaker = text(obj.get("speaker", ""), 60, True)
        split = obj.get("split", "train")
        if split not in ("train", "dev", "test"):
            raise ValueError("数据集划分无效。")
        other = self.db.execute("SELECT split FROM samples WHERE speaker=? LIMIT 1", (speaker,)).fetchone()
        if other and other[0] != split:
            raise ValueError("同一说话人不能跨 train/dev/test，以免评测泄漏。")
        digest = hashlib.sha256(raw).hexdigest()
        if any(s["audio_sha256"] == digest for s in self.samples()):
            raise ValueError("这段音频已保存，不能重复进入评测集。")
        meta = {"id": uuid.uuid4().hex, "speaker": speaker, "split": split, "seconds": seconds,
                "district": text(obj.get("district", ""), 60, True), "reference": text(obj.get("reference", ""), 3000, True),
                "mandarin": text(obj.get("mandarin", ""), 3000), "raw_asr": text(obj.get("raw_asr", ""), 6000),
                "model": text(obj.get("model", "manual"), 100), "audio_sha256": digest, "reviewed": True, "consent": True,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        with self.db:
            self.db.execute("INSERT INTO samples VALUES (?,?,?,?,?)", (meta["id"], speaker, split, json.dumps(meta, ensure_ascii=False), raw))
        return meta
    def remove_sample(self, ident):
        with self.db:
            self.db.execute("DELETE FROM samples WHERE id=?", (ident,))
    def export(self):
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("corpus.json", json.dumps(self.corpus(), ensure_ascii=False, indent=2))
            lines = []
            for ident, metadata, audio in self.db.execute("SELECT id,meta,audio FROM samples"):
                m = json.loads(metadata)
                m["audio"] = f"audio/{ident}.wav"
                z.writestr(m["audio"], audio)
                lines.append(json.dumps(m, ensure_ascii=False))
            z.writestr("manifest.jsonl", "\n".join(lines))
            z.writestr("NOTICE.txt", "Private, consented data. Not fine-tuned. Keep test speakers out of training and prompts.\n")
        return out.getvalue()
    def close(self):
        self.db.close()
