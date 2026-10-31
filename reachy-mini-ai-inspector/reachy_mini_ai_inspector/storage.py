import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import threading
import uuid


def now():
    return datetime.now(timezone.utc).isoformat()


def safe_cell(value):
    value = str(value if value is not None else "")
    return "'"+value if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else value


class Store:
    def __init__(self, path, mode):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.images = self.path / "images"
        self.images.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path / "inspections.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS inspections (id TEXT PRIMARY KEY, created_at TEXT, record TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS refs (id TEXT PRIMARY KEY, profile TEXT, record TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS criteria (id TEXT PRIMARY KEY, record TEXT NOT NULL)")
        existing = self.get_meta("mode")
        if existing and existing != mode:
            raise ValueError("デモと実機のデータ保存先を分けてください")
        self.set_meta("mode", mode)

    def get_meta(self, key):
        with self.lock:
            row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else None

    def set_meta(self, key, value):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))

    def save_image(self, data, prefix):
        name = f"{prefix}-{uuid.uuid4().hex}.jpg"
        destination = self.images / name
        temporary = destination.with_suffix(".tmp")
        temporary.write_bytes(data)
        temporary.replace(destination)
        return name

    def criteria(self):
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute("SELECT record FROM criteria ORDER BY rowid")]

    def criterion(self, id):
        with self.lock:
            row = self.db.execute("SELECT record FROM criteria WHERE id=?", (id,)).fetchone()
            if row is None:
                raise KeyError(id)
            return json.loads(row[0])

    def add_criterion(self, name, settings):
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError("検査基準名を1〜80文字で入力してください")
        with self.lock, self.db:
            if any(c["name"] == name for c in self.criteria()):
                raise ValueError("同じ名前の検査基準があります。別の名前を入力してください")
            record = {"id": uuid.uuid4().hex, "name": name, "created_at": now(),
                      "settings": {**settings, "normal_name": name}}
            self.db.execute("INSERT INTO criteria VALUES (?,?)", (record["id"], json.dumps(record, ensure_ascii=False)))
            return record

    def update_criterion(self, id, settings):
        name = settings["normal_name"].strip()
        if not name:
            raise ValueError("検査基準名を入力してください")
        with self.lock, self.db:
            if any(c["name"] == name and c["id"] != id for c in self.criteria()):
                raise ValueError("同じ名前の検査基準があります。別の名前を入力してください")
            record = {**self.criterion(id), "name": name, "settings": {**settings, "normal_name": name}}
            self.db.execute("UPDATE criteria SET record=? WHERE id=?", (json.dumps(record, ensure_ascii=False), id))
            return record

    def migrate_criteria(self, settings):
        """Attach legacy reference sets to stable IDs without changing images/history."""
        from .settings import Settings
        with self.lock, self.db:
            rows = self.db.execute("SELECT DISTINCT profile FROM refs").fetchall()
            for (encoded,) in rows:
                old = json.loads(encoded)
                if "criterion_id" in old:
                    continue
                if old.get("features") != "hsv-shape-v1":
                    raise ValueError("既存の正解画像の形式を確認してください")
                name = old.get("normal_name", "以前の検査基準")
                existing = {c["name"] for c in self.criteria()}
                candidate, suffix = name, 2
                while candidate in existing:
                    candidate = f"{name[:65]}（旧設定{suffix}）"
                    suffix += 1
                migrated = settings.model_copy(update={"roi": Settings(roi=old["roi"]).roi, "normal_name": candidate})
                # Insert directly so the whole migration stays in this transaction.
                record = {"id": uuid.uuid4().hex, "name": candidate, "created_at": now(), "settings": migrated.model_dump()}
                self.db.execute("INSERT INTO criteria VALUES (?,?)", (record["id"], json.dumps(record, ensure_ascii=False)))
                self.db.execute("UPDATE refs SET profile=? WHERE profile=?", (json.dumps(migrated.profile(record["id"]), sort_keys=True), encoded))
                if old == settings.profile() and not self.get_meta("active_criterion_id"):
                    self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", ("active_criterion_id", json.dumps(record["id"])))
            if not self.get_meta("active_criterion_id"):
                criteria = self.criteria()
                if len(criteria) == 1:
                    self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", ("active_criterion_id", json.dumps(criteria[0]["id"])))

    def refs(self, profile):
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute("SELECT record FROM refs WHERE profile=? ORDER BY rowid", (json.dumps(profile, sort_keys=True),))]

    def add_ref(self, profile, data, features, measures, source="camera", original_name=""):
        sha = hashlib.sha256(data).hexdigest()
        if any(r["sha256"] == sha for r in self.refs(profile)):
            raise ValueError("同じ画像は登録済みです。別の画像を選ぶか、撮影し直してください")
        record = {"id": uuid.uuid4().hex, "created_at": now(), "sha256": sha,
                  "image": self.save_image(data, "normal"), "features": features.tolist(), "measurements": measures,
                  "source": source, "original_name": original_name}
        with self.lock, self.db:
            self.db.execute("INSERT INTO refs VALUES (?,?,?)", (record["id"], json.dumps(profile, sort_keys=True), json.dumps(record)))
        return record

    def add_result(self, record, data):
        record = {**record, "id": uuid.uuid4().hex[:12], "created_at": now(), "image": self.save_image(data, "inspection"),
                  "sha256": hashlib.sha256(data).hexdigest(), "truth": None, "condition": "", "motion": {"performed": False, "reason": "未実行"},
                  "sound": {"performed": False, "reason": "未実行"}}
        with self.lock, self.db:
            self.db.execute("INSERT INTO inspections VALUES (?,?,?)", (record["id"], record["created_at"], json.dumps(record, ensure_ascii=False)))
        return record

    def update(self, id, changes):
        with self.lock, self.db:
            row = self.db.execute("SELECT record FROM inspections WHERE id=?", (id,)).fetchone()
            if not row:
                raise KeyError(id)
            record = {**json.loads(row[0]), **changes}
            self.db.execute("UPDATE inspections SET record=? WHERE id=?", (json.dumps(record, ensure_ascii=False), id))
            return record

    def history(self, limit=100, offset=0):
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute("SELECT record FROM inspections ORDER BY rowid DESC LIMIT ? OFFSET ?", (limit, offset))]

    def metrics(self):
        rows = [r for r in self.history(-1) if r["truth"] in ("OK", "NG")]
        n = len(rows)
        normals = [r for r in rows if r["truth"] == "OK"]
        defects = [r for r in rows if r["truth"] == "NG"]
        ratio = lambda a, b: round(a/b, 4) if b else None
        return {"labeled": n, "normal_count": len(normals), "defect_count": len(defects),
                "accuracy": ratio(sum(r["verdict"] == r["truth"] for r in rows), n),
                "normal_recall": ratio(sum(r["verdict"] == "OK" for r in normals), len(normals)),
                "defect_recall": ratio(sum(r["verdict"] == "NG" for r in defects), len(defects)),
                "false_rejects": sum(r["verdict"] == "NG" for r in normals),
                "missed_defects": sum(r["verdict"] == "OK" for r in defects),
                "reviews": sum(r["verdict"] == "REVIEW" for r in rows),
                "coverage": ratio(sum(r["verdict"] != "REVIEW" for r in rows), n)}

    def csv(self):
        stream = io.StringIO()
        fields = ["id", "identifier", "created_at", "mode", "criterion_id", "criterion_name", "verdict", "reasons", "ai_score", "svm_decision",
                  "ai_executed", "model_id", "inference_ms", "image", "sha256", "settings", "truth", "condition", "motion", "sound"]
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for record in self.history(-1):
            writer.writerow({key: safe_cell(json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value) for key, value in record.items() if key in fields})
        return "\ufeff" + stream.getvalue()

    def close(self):
        self.db.close()
