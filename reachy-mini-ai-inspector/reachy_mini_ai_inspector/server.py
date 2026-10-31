from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
import threading
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .providers import decode, demo_image, encode
from .settings import Settings
from .storage import Store
from .vision import AnomalyModel, MIN_REFERENCES, extract
from .reference_images import MAX_BATCH_BYTES, MAX_FILE_BYTES, MAX_FILES, normalize_reference


class Inspector:
    def __init__(self, provider, data_dir):
        self.provider = provider
        self.store = Store(data_dir, provider.mode)
        self.settings = Settings.model_validate(self.store.get_meta("settings") or {})
        self.store.migrate_criteria(self.settings)
        self.active_id = self.store.get_meta("active_criterion_id")
        if self.active_id:
            self.settings = Settings.model_validate(self.store.criterion(self.active_id)["settings"])
        self.lock = threading.Lock()
        self.model = None
        saved_sound = self.store.get_meta("sound_enabled")
        self.sound_enabled = True if saved_sound is None else bool(saved_sound)
        self.rebuild()

    def rebuild(self):
        refs = self.store.refs(self.profile()) if self.active_id else []
        self.model = AnomalyModel(refs, self.profile())

    def profile(self):
        return self.settings.profile(self.active_id)

    def require_criterion(self):
        if not self.active_id:
            raise HTTPException(409, "検査基準を作成して選択してください")

    def select_criterion(self, id):
        criterion = self.store.criterion(id)
        try:
            self.provider.motion(False)
        except RuntimeError:
            pass
        self.active_id = id
        self.settings = Settings.model_validate(criterion["settings"])
        self.store.set_meta("active_criterion_id", id)
        self.store.set_meta("settings", self.settings.model_dump())
        self.rebuild()
        return criterion

    def create_criterion(self, name):
        criterion = self.store.add_criterion(name, self.settings.model_dump())
        return self.select_criterion(criterion["id"])

    @contextmanager
    def operation(self):
        if not self.lock.acquire(blocking=False):
            raise HTTPException(409, "撮影・学習・検査の処理中です")
        try:
            yield
        finally:
            self.lock.release()

    def register(self):
        self.require_criterion()
        data = self.provider.frame(fresh=True)
        self.add_reference(data, "camera")
        self.rebuild()
        return {"count": len(self.model.references), "ready": self.model.model is not None}

    def add_reference(self, data, source, original_name=""):
        data = normalize_reference(data)
        features, measures, issues = extract(decode(data), self.settings)
        if issues:
            raise ValueError(" / ".join(issues))
        return self.store.add_ref(self.profile(), data, features, measures, source, original_name)

    def inspect(self, identifier):
        self.require_criterion()
        data = self.provider.frame(fresh=True)
        prediction = self.model.predict(decode(data), self.settings)
        record = self.store.add_result({**prediction, "identifier": identifier,
                                       "criterion_id": self.active_id, "criterion_name": self.settings.normal_name,
                                       "settings": self.settings.model_dump(), "mode": self.provider.mode}, data)
        sound = self.play_sound(record["verdict"])
        self.store.update(record["id"], {"sound": sound})
        try:
            motion = self.provider.react(record["verdict"])
        except RuntimeError as exc:
            motion = {"performed": False, "reason": str(exc)}
        return self.store.update(record["id"], {"motion": motion})

    def play_sound(self, verdict):
        if not self.sound_enabled:
            return {"performed": False, "reason": "判定音OFF"}
        try:
            return self.provider.sound(verdict)
        except RuntimeError as exc:
            return {"performed": False, "reason": "判定音の送信に失敗：" + str(exc)}


def create_app(provider, data_dir):
    inspector = Inspector(provider, data_dir)

    @asynccontextmanager
    async def lifespan(app):
        yield
        provider.close()
        inspector.store.close()

    app = FastAPI(title="Reachy Mini AI Inspector", lifespan=lifespan)
    app.state.inspector = inspector
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])

    @app.middleware("http")
    async def local_actions(request: Request, call_next):
        if request.method in ("POST", "PUT", "DELETE"):
            origin = request.headers.get("origin")
            expected = f"{request.url.scheme}://{request.headers.get('host')}"
            if request.headers.get("x-inspector-ui") != "1" or (origin and origin != expected):
                return Response("ローカル画面から操作してください", status_code=403)
            length = request.headers.get("content-length", "0")
            if length.isdigit() and int(length) > MAX_BATCH_BYTES + 1024 * 1024:
                return Response("1回に読み込める画像は合計50MB以下です", status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(RuntimeError)
    async def runtime_error(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": str(exc)}, status_code=422)

    static = Path(__file__).parent / "dashboard"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    @app.get("/api/status")
    def status():
        try:
            robot = provider.health()
        except RuntimeError as exc:
            robot = {"connected": False, "camera_ready": False, "motion_enabled": False, "error": str(exc)}
        return {"mode": provider.mode, "robot": robot, "busy": inspector.lock.locked(),
                "sound_enabled": inspector.sound_enabled,
                "normal_count": len(inspector.model.references), "model_ready": inspector.model.model is not None,
                "model_id": inspector.model.model_id, "minimum_references": MIN_REFERENCES,
                "active_criterion": {"id": inspector.active_id, "name": inspector.settings.normal_name} if inspector.active_id else None,
                "settings": inspector.settings.model_dump()}

    def get_criterion(id):
        try:
            return inspector.store.criterion(id)
        except KeyError:
            raise HTTPException(404, "検査基準が見つかりません") from None

    @app.get("/api/criteria")
    def criteria():
        rows = []
        for criterion in inspector.store.criteria():
            count = len(inspector.store.refs(Settings.model_validate(criterion["settings"]).profile(criterion["id"])))
            rows.append({**criterion, "count": count, "ready": count >= MIN_REFERENCES})
        return rows

    class CriterionName(BaseModel):
        name: str = Field(min_length=1, max_length=80)

    @app.post("/api/criteria")
    def create_criterion(body: CriterionName):
        with inspector.operation():
            return inspector.create_criterion(body.name)

    class CriterionSelection(BaseModel):
        id: str

    @app.post("/api/criteria/select")
    def select_criterion(body: CriterionSelection):
        with inspector.operation():
            get_criterion(body.id)
            return inspector.select_criterion(body.id)

    @app.get("/api/criteria/{id}/references")
    def references(id: str):
        criterion = get_criterion(id)
        profile = Settings.model_validate(criterion["settings"]).profile(id)
        rows = inspector.store.refs(profile)
        return {"count": len(rows), "ready": len(rows) >= MIN_REFERENCES,
                "images": [{key: r.get(key, "") for key in ("id", "image", "created_at", "source", "original_name")} for r in rows]}

    @app.post("/api/criteria/{id}/references")
    async def import_references(id: str, files: list[UploadFile] = File(...)):
        with inspector.operation():
            get_criterion(id)
            if id != inspector.active_id:
                raise HTTPException(409, "画像を登録する検査基準を先に選択してください")
            if len(files) > MAX_FILES:
                raise HTTPException(422, "1回に読み込める画像は20枚までです")
            accepted, errors, total = [], [], 0
            try:
                for file in files:
                    name = (file.filename or "画像").replace("\\", "/").rsplit("/", 1)[-1][:120]
                    data = await file.read(MAX_FILE_BYTES + 1)
                    total += len(data)
                    if total > MAX_BATCH_BYTES:
                        errors.append({"name": name, "reason": "1回の読み込みは合計50MB以下にしてください"})
                        break
                    try:
                        reference = inspector.add_reference(data, "upload", name)
                        accepted.append({"id": reference["id"], "name": name})
                    except ValueError as exc:
                        errors.append({"name": name, "reason": str(exc)})
            finally:
                for file in files:
                    await file.close()
                inspector.rebuild()
            return {"accepted": accepted, "errors": errors, "count": len(inspector.model.references),
                    "ready": inspector.model.model is not None}

    @app.get("/api/frame")
    def frame():
        return Response(provider.frame(), media_type="image/jpeg")

    @app.post("/api/snapshot")
    def snapshot():
        with inspector.operation():
            data = provider.frame(fresh=True)
            image = inspector.store.save_image(data, "snapshot")
            return {"image": image}

    @app.get("/api/images/{name}")
    def image(name: str):
        if not name.endswith(".jpg") or Path(name).name != name:
            raise HTTPException(404)
        path = inspector.store.images / name
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path)

    @app.post("/api/settings")
    def settings(body: Settings):
        with inspector.operation():
            if inspector.active_id:
                criterion = inspector.store.update_criterion(inspector.active_id, body.model_dump())
                body = Settings.model_validate(criterion["settings"])
            inspector.store.set_meta("settings", body.model_dump())
            inspector.settings = body
            inspector.rebuild()
            return body.model_dump()

    @app.post("/api/normal")
    def register():
        with inspector.operation():
            return inspector.register()

    class Inspection(BaseModel):
        identifier: str = Field(default="", max_length=80)

    @app.post("/api/inspect")
    def inspect(body: Inspection):
        with inspector.operation():
            return inspector.inspect(body.identifier.strip())

    class Motion(BaseModel):
        enabled: bool
        physically_checked: bool = False

    @app.post("/api/motion")
    def motion(body: Motion):
        # Disabling is always available, including during an inspection.
        if not body.enabled:
            return provider.motion(False)
        if not body.physically_checked:
            raise HTTPException(422, "実機周囲を確認してください")
        with inspector.operation():
            return provider.motion(True, True)

    class SoundSetting(BaseModel):
        enabled: bool

    @app.post("/api/sound")
    def sound_setting(body: SoundSetting):
        with inspector.operation():
            inspector.store.set_meta("sound_enabled", body.enabled)
            inspector.sound_enabled = body.enabled
            return {"enabled": body.enabled}

    class SoundTest(BaseModel):
        verdict: Literal["OK", "NG", "REVIEW"] = "OK"

    @app.post("/api/sound/test")
    def sound_test(body: SoundTest):
        with inspector.operation():
            return inspector.play_sound(body.verdict)

    @app.post("/api/position/remember")
    def remember_position():
        with inspector.operation():
            return provider.remember_position()

    class ReturnPosition(BaseModel):
        physically_checked: bool = False

    @app.post("/api/position/return")
    def return_position(body: ReturnPosition):
        if not body.physically_checked:
            raise HTTPException(422, "実機周囲を確認してください")
        with inspector.operation():
            return provider.return_position()

    class Scene(BaseModel):
        scene: Literal["red24", "blue24", "red28", "empty", "blur"]

    @app.post("/api/demo/scene")
    def scene(body: Scene):
        if provider.mode != "demo":
            raise HTTPException(404)
        with inspector.operation():
            provider.scene = body.scene
            return {"scene": body.scene}

    @app.post("/api/demo/train")
    def train_demo():
        if provider.mode != "demo":
            raise HTTPException(404)
        with inspector.operation():
            if not inspector.active_id:
                inspector.create_criterion("デモ基準")
            for seed in range(100, 112):
                data = encode(demo_image("red24", seed))
                features, measures, issues = extract(decode(data), inspector.settings)
                if issues:
                    raise ValueError("デモ用の標準ROIに戻してください")
                try:
                    inspector.store.add_ref(inspector.profile(), data, features, measures, "demo")
                except ValueError:
                    pass
            inspector.rebuild()
            return {"count": len(inspector.model.references)}

    @app.get("/api/history")
    def history(offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100)):
        return inspector.store.history(limit, offset)

    class Label(BaseModel):
        truth: Literal["OK", "NG"] | None
        condition: str = Field(default="", max_length=120)

    @app.post("/api/history/{id}/label")
    def label(id: str, body: Label):
        try:
            return inspector.store.update(id, body.model_dump())
        except KeyError:
            raise HTTPException(404) from None

    @app.get("/api/metrics")
    def metrics():
        return {"mode": provider.mode, **inspector.store.metrics()}

    @app.get("/api/export.csv")
    def export():
        return Response(inspector.store.csv(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="inspections.csv"'})

    return app
