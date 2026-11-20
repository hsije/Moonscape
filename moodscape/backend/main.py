from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text
from typing import Dict, Any, List, Optional
import json
from datetime import datetime, timezone

from database import engine, get_db, SessionLocal
import models, schemas
from services.ai_service import AIService, OBSERVER_LINES
from services.audio_service import analyze_voice_tone, analyze_song

models.Base.metadata.create_all(bind=engine)


def _migrate() -> None:
    """Lightweight SQLite migration: backfill columns CREATE_ALL won't add."""
    insp = inspect(engine)
    for table, cols_needed in {
        "mood_islands": {"ecology": "JSON DEFAULT '{}'", "sediment_layers": "JSON DEFAULT '[]'"},
        "users": {"premium_tier": "VARCHAR DEFAULT 'free'", "entitlements": "JSON DEFAULT '{}'"},
        "drift_bottles": {"recipient_id": "INTEGER"},
    }.items():
        if table not in insp.get_table_names():
            continue
        cols = {c["name"] for c in insp.get_columns(table)}
        with engine.begin() as conn:
            for col, ddl in cols_needed.items():
                if col not in cols:
                    conn.execute(text("ALTER TABLE " + table + " ADD COLUMN " + col + " " + ddl))


_migrate()

app = FastAPI(title="Moodscape API")
ai_service = AIService()


# --- 在场管理 (投影光学浓度) ------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.active: Dict[int, WebSocket] = {}
        self.presence: Dict[int, float] = {}  # 光学浓度 0..1

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active[user_id] = websocket
        self.presence[user_id] = 0.0

    def disconnect(self, user_id: int):
        self.active.pop(user_id, None)
        self.presence.pop(user_id, None)

    def set_presence(self, user_id: int, level: float):
        self.presence[user_id] = max(0.0, min(1.0, level))

    async def broadcast(self, user_id: int, data: dict, partners: Optional[List[int]] = None):
        targets = partners if partners is not None else [u for u in self.active if u != user_id]
        for uid in targets:
            conn = self.active.get(uid)
            if conn:
                try:
                    await conn.send_json(data)
                except Exception:
                    pass


manager = ConnectionManager()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- 工具函数 -----------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fresh_stats() -> Dict[str, Any]:
    return {"frequency_map": {}, "growth_status": "stable", "total_entries": 0}


def _evolve(island: models.MoodIsland, mood: str, connection: bool = False) -> None:
    """Accumulate long-term evolution + ecological niches from recurring moods.

    生态位有容量上限：岛屿会生长，但不会因为反复输入而无限堆叠。
    """
    CAP = 8  # 单个生态位的容量上限

    stats = dict(island.evolution_stats or _fresh_stats())
    freq = dict(stats.get("frequency_map", {}))
    freq[mood] = freq.get(mood, 0) + 1
    stats["frequency_map"] = freq
    stats["total_entries"] = sum(freq.values())

    eco = dict(island.ecology or {"niches": {}, "resources": {}})
    niches = dict(eco.get("niches", {}))

    def grow(key: str, step: int = 1) -> None:
        niches[key] = min(CAP, niches.get(key, 0) + step)

    # 反复情绪催生特定生态位
    if freq.get("anxious", 0) >= 3:
        grow("wind-eroded_cliff")
        grow("crystals")
    if freq.get("lonely", 0) >= 3:
        grow("echo_cave")
    if freq.get("happy", 0) >= 2:
        grow("ephemeral_blooms")
        niches.setdefault("seed_layer", 1)  # 喜悦留下种子层

    # 焦虑晶体被平静"风化"为卵石苔藓
    if mood == "calm" and niches.get("crystals", 0):
        grow("pebble_moss")
        niches["crystals"] = max(0, niches["crystals"] - 1)
        if niches["crystals"] == 0:
            niches.pop("crystals", None)

    # 回声洞穴被连接感覆盖后转为发光菌丝（由陪伴触发，而非喜悦）
    if connection and niches.get("echo_cave", 0):
        grow("glowing_mycelium")
        niches["echo_cave"] = max(0, niches["echo_cave"] - 1)
        if niches["echo_cave"] == 0:
            niches.pop("echo_cave", None)

    eco["niches"] = niches

    status = "stable"
    if freq.get("calm", 0) > 3:
        status = "forest_growth"
    elif freq.get("happy", 0) > 5:
        status = "habitat_expansion"
    stats["growth_status"] = status

    island.evolution_stats = stats
    island.ecology = eco


def _bond_partners(user_id: int, db: Session) -> List[int]:
    bonds = db.query(models.Bond).filter(
        models.Bond.status == "active",
        ((models.Bond.user_a == user_id) | (models.Bond.user_b == user_id)),
    ).all()
    out = []
    for b in bonds:
        out.append(b.user_b if b.user_a == user_id else b.user_a)
    return out


def _persist_mood(text: str, params: Dict[str, Any], prompt: str, user_id: Optional[int], db: Session, source: str = "text") -> models.MoodIsland:
    """Shared island persistence for /analyze, /analyze/voice, /analyze/song."""
    island = None
    if user_id:
        island = (
            db.query(models.MoodIsland)
            .filter(models.MoodIsland.user_id == user_id, models.MoodIsland.is_active.is_(True))
            .order_by(models.MoodIsland.id.desc()).first()
        )
    if island is None:
        island = models.MoodIsland(user_id=user_id)
        db.add(island)

    island.text_input = text
    island.visual_params = params
    island.ai_prompt = prompt
    island.last_interacted = _now()

    _evolve(island, params["mood"])

    layers = list(island.sediment_layers or [])
    layers.append({
        "layer": len(layers),
        "mood": params["mood"],
        "text": text,
        "source": source,
        "energy": params["energy"],
        "valence": params["valence"],
        "tension": params["tension"],
        "clarity": params["clarity"],
        "released": False,
        "created_at": _now_iso(),
    })
    island.sediment_layers = layers

    db.commit()
    db.refresh(island)
    return island


def _island_response(island: models.MoodIsland) -> Dict[str, Any]:
    return {
        "id": island.id,
        "text": island.text_input,
        "visual_params": island.visual_params,
        "ai_prompt": island.ai_prompt,
        "evolution": island.evolution_stats,
        "created_at": island.created_at,
    }


def build_memorial_tree(params: Dict[str, Any]) -> str:
    """纪念树形态：由岛屿快照生成可打印的 SVG。"""
    palette = params.get("palette", ["#B2F5EA", "#81E6D9", "#C6F6D5"])
    mood = params.get("mood", "neutral")
    primary = palette[0] if palette else "#B2F5EA"
    accent = palette[2] if len(palette) > 2 else primary
    layers_n = {"anxious": 3, "calm": 5, "lonely": 2, "happy": 6, "sad": 3, "neutral": 4}.get(mood, 4)
    circles = []
    for i in range(layers_n):
        r = 70 - i * 9
        cy = 140 - i * 30
        circles.append('<circle cx="200" cy="' + str(cy) + '" r="' + str(r) + '" fill="' + primary + '" fill-opacity="0.55"/>')
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="220" viewBox="0 0 400 220">'
        '<rect width="400" height="220" fill="#0a0a12"/>'
        '<rect x="188" y="150" width="24" height="60" rx="6" fill="' + accent + '"/>'
        + ''.join(circles) +
        '<text x="200" y="210" text-anchor="middle" fill="#ffffff" font-size="12" opacity="0.7">' + mood + '</text>'
        '</svg>'
    )


# --- 情绪输入（文字 / 语音 / 歌曲）--------------------------------------------

@app.get("/")
async def root():
    return {"message": "Welcome to Moodscape API.", "docs": "/docs"}


@app.post("/users", response_model=schemas.UserResponse)
async def register(user: schemas.UserCreate, db: Session = Depends(get_db)):
    """极简注册（本切片无真实鉴权，密码仅占位）。"""
    existing = db.query(models.User).filter(models.User.username == user.username).first()
    if existing:
        return {"id": existing.id, "username": existing.username, "created_at": existing.created_at}
    u = models.User(username=user.username, hashed_password=user.password)
    db.add(u); db.commit(); db.refresh(u)
    return {"id": u.id, "username": u.username, "created_at": u.created_at}


@app.post("/analyze", response_model=schemas.MoodResponse)
async def analyze_mood(request: schemas.MoodRequest, db: Session = Depends(get_db)):
    user = None
    if request.user_id:
        user = db.query(models.User).filter(models.User.id == request.user_id).first()
    is_premium = bool(user and user.is_premium)

    params = ai_service.analyze_emotion(request.text, is_premium=is_premium, theme_pref=request.theme)
    prompt = ai_service.generate_ai_prompt(params)
    island = _persist_mood(request.text, params, prompt, request.user_id, db, source="text")
    return _island_response(island)


@app.post("/analyze/voice", response_model=schemas.MoodResponse)
async def analyze_voice(file: UploadFile = File(...), user_id: Optional[int] = Form(None), db: Session = Depends(get_db)):
    audio = await file.read()
    tone = analyze_voice_tone(audio, file.filename or "")
    # 语义优先：若转写文本含情绪词，用语义引擎；否则用语调（能量→唤醒度）
    params = ai_service.engine.analyze(tone["transcript"])
    if params["mood"] == "neutral":
        params = ai_service.engine.from_vad(tone["valence"], tone["energy"], tone["tension"])
    prompt = ai_service.generate_ai_prompt(params)
    island = _persist_mood(tone["transcript"], params, prompt, user_id, db, source="voice")
    return _island_response(island)


@app.post("/analyze/song", response_model=schemas.MoodResponse)
async def analyze_song_endpoint(file: UploadFile = File(...), user_id: Optional[int] = Form(None), db: Session = Depends(get_db)):
    audio = await file.read()
    feats = analyze_song(audio, file.filename or "")
    params = ai_service.engine.from_vad(feats["valence"], feats["energy"], feats["tension"])
    prompt = ai_service.generate_ai_prompt(params)
    label = "歌曲 · " + (file.filename or "未命名")
    island = _persist_mood(label, params, prompt, user_id, db, source="song")
    return _island_response(island)


# --- 岛屿 / 情绪清理 ---------------------------------------------------------

@app.get("/island/{user_id}")
async def get_island(user_id: int, db: Session = Depends(get_db)):
    island = (
        db.query(models.MoodIsland)
        .filter(models.MoodIsland.user_id == user_id, models.MoodIsland.is_active.is_(True))
        .order_by(models.MoodIsland.id.desc()).first()
    )
    if not island:
        raise HTTPException(status_code=404, detail="Island not found")
    return {
        "id": island.id,
        "user_id": island.user_id,
        "visual_params": island.visual_params,
        "evolution_stats": island.evolution_stats,
        "ecology": island.ecology,
        "sediment_layers": island.sediment_layers,
        "created_at": island.created_at,
        "last_interacted": island.last_interacted,
    }


@app.post("/release", response_model=schemas.ReleaseResponse)
async def release(request: schemas.ReleaseRequest, db: Session = Depends(get_db)):
    island = db.query(models.MoodIsland).filter(models.MoodIsland.id == request.island_id).first()
    if not island:
        raise HTTPException(status_code=404, detail="Island not found")

    resources = {
        "anxious": "地热 geothermal_veins",
        "sad": "温泉 hot_springs",
        "lonely": "玄武岩地基 basalt_foundation",
    }
    resource = resources.get(request.emotion, "玄武岩地基 basalt_foundation")

    eco = dict(island.ecology or {"niches": {}, "resources": {}})
    res = dict(eco.get("resources", {}))
    res[resource] = res.get(resource, 0) + 1
    eco["resources"] = res
    island.ecology = eco

    layers = list(island.sediment_layers or [])
    layers.append({"layer": len(layers), "mood": request.emotion, "released": True, "resource": resource, "created_at": _now_iso()})
    island.sediment_layers = layers
    island.last_interacted = _now()
    db.commit()

    return {"island_id": island.id, "resource": resource, "sediment_layer": layers[-1], "message": "负面情绪已转化为岛屿资源，未被删除。"}


# --- 社交层：静默陪伴 ---------------------------------------------------------

@app.post("/bond", response_model=schemas.BondResponse)
async def create_bond(request: schemas.BondRequest, db: Session = Depends(get_db)):
    # 付费仪式化为桥墩出现，对方主动"回应"后桥才生成
    existing = db.query(models.Bond).filter(
        ((models.Bond.user_a == request.user_a) & (models.Bond.user_b == request.user_b)) |
        ((models.Bond.user_a == request.user_b) & (models.Bond.user_b == request.user_a))
    ).first()
    if existing:
        return {"id": existing.id, "user_a": existing.user_a, "user_b": existing.user_b, "status": existing.status}
    bond = models.Bond(user_a=request.user_a, user_b=request.user_b, status="pending")
    db.add(bond); db.commit(); db.refresh(bond)
    return {"id": bond.id, "user_a": bond.user_a, "user_b": bond.user_b, "status": bond.status}


@app.post("/bond/{bond_id}/respond", response_model=schemas.BondResponse)
async def respond_bond(bond_id: int, user_id: int, db: Session = Depends(get_db)):
    """桥由受邀方本人回应后才生成；发起方不能代替对方点头。"""
    bond = db.query(models.Bond).filter(models.Bond.id == bond_id).first()
    if not bond:
        raise HTTPException(status_code=404, detail="Bond not found")
    if user_id != bond.user_b:
        raise HTTPException(
            status_code=403,
            detail="只有受邀方本人可以回应：桥不能由发起方单方面建立。",
        )
    bond.status = "active"
    db.commit()
    return {"id": bond.id, "user_a": bond.user_a, "user_b": bond.user_b, "status": bond.status}


@app.get("/bond/invites/{user_id}")
async def list_invites(user_id: int, db: Session = Depends(get_db)):
    """待我本人回应的邀请（我是受邀方且尚未回应）。"""
    invites = (
        db.query(models.Bond)
        .filter(models.Bond.user_b == user_id, models.Bond.status == "pending")
        .order_by(models.Bond.id.asc())
        .all()
    )
    return [{"id": b.id, "user_a": b.user_a, "user_b": b.user_b, "status": b.status} for b in invites]


@app.get("/bond/{bond_id}/bridge")
async def bridge_status(bond_id: int, db: Session = Depends(get_db)):
    bond = db.query(models.Bond).filter(models.Bond.id == bond_id).first()
    if not bond:
        raise HTTPException(status_code=404, detail="Bond not found")
    a, b = bond.user_a, bond.user_b
    a_on = manager.presence.get(a, 0) > 0.3
    b_on = manager.presence.get(b, 0) > 0.3
    level = (manager.presence.get(a, 0) + manager.presence.get(b, 0)) / 2
    # pending 阶段只有桥墩：付费仪式化为桥墩出现，对方回应后桥才可能凝固
    if bond.status != "active":
        bridge = "pier"
    elif a_on and b_on and level >= 0.5:
        bridge = "frozen"
    else:
        bridge = "liquid"
    return {"bridge": bridge, "status": bond.status, "a_online": a_on, "b_online": b_on, "a_level": manager.presence.get(a, 0), "b_level": manager.presence.get(b, 0), "level": round(level, 3)}


@app.post("/bottle", response_model=schemas.BottleResponse)
async def send_bottle(request: schemas.BottleRequest, db: Session = Depends(get_db)):
    bottle = models.DriftBottle(
        sender_id=request.sender_id,
        island_id=request.island_id,
        recipient_id=request.recipient_id,
        snippet=request.snippet,
        ambience=request.ambience,
    )
    db.add(bottle); db.commit(); db.refresh(bottle)
    return {"id": bottle.id, "sender_id": bottle.sender_id, "ambience": bottle.ambience, "snippet": bottle.snippet, "created_at": bottle.created_at}


@app.get("/bottle/{user_id}")
async def receive_bottles(user_id: int, db: Session = Depends(get_db)):
    """收件箱：定向投放给我的，或仍在漂流、尚未被任何人拾取的瓶子。

    每次最多浮现一只，避免"未读堆积"变成另一种红点压力。
    """
    bottle = (
        db.query(models.DriftBottle)
        .filter(
            models.DriftBottle.sender_id != user_id,
            models.DriftBottle.opened_by.is_(None),
            ((models.DriftBottle.recipient_id == user_id) | (models.DriftBottle.recipient_id.is_(None))),
        )
        .order_by(models.DriftBottle.id.asc())
        .first()
    )
    if not bottle:
        return []
    return [{"id": bottle.id, "sender_id": bottle.sender_id, "ambience": bottle.ambience, "snippet": bottle.snippet, "created_at": bottle.created_at}]


@app.post("/bottle/{bottle_id}/open")
async def open_bottle(bottle_id: int, user_id: int, db: Session = Depends(get_db)):
    bottle = db.query(models.DriftBottle).filter(models.DriftBottle.id == bottle_id).first()
    if not bottle:
        raise HTTPException(status_code=404, detail="Bottle not found")
    if bottle.sender_id == user_id:
        raise HTTPException(status_code=403, detail="不能打开自己投放的瓶子。")
    if bottle.recipient_id is not None and bottle.recipient_id != user_id:
        raise HTTPException(status_code=403, detail="这只瓶子漂向了别人。")
    if bottle.opened_by is not None and bottle.opened_by != user_id:
        raise HTTPException(status_code=409, detail="这只瓶子已经被别人拾起。")
    bottle.opened_by = user_id
    bottle.opened_at = _now()
    db.commit()
    return {"id": bottle.id, "ambience": bottle.ambience, "snippet": bottle.snippet, "opened": True}


@app.post("/action", response_model=schemas.ActionResponse)
async def do_action(request: schemas.ActionRequest, db: Session = Depends(get_db)):
    """低压互动：点灯 / 种花。被陪伴者岛上的回声洞穴因此转为发光菌丝。"""
    bond = db.query(models.Bond).filter(models.Bond.id == request.bond_id).first()
    if not bond:
        raise HTTPException(status_code=404, detail="Bond not found")
    if request.actor_id not in (bond.user_a, bond.user_b):
        raise HTTPException(status_code=403, detail="Not a participant")
    if bond.status != "active":
        raise HTTPException(status_code=409, detail="桥尚未生成：对方还没有回应。")

    act = models.IslandAction(bond_id=request.bond_id, actor_id=request.actor_id, kind=request.kind)
    db.add(act)

    # 连接感覆盖：接收方（非动作发起者）岛上的回声洞穴转为发光菌丝
    receiver = bond.user_b if request.actor_id == bond.user_a else bond.user_a
    island = (
        db.query(models.MoodIsland)
        .filter(models.MoodIsland.user_id == receiver, models.MoodIsland.is_active.is_(True))
        .order_by(models.MoodIsland.id.desc()).first()
    )
    if island:
        eco = dict(island.ecology or {"niches": {}, "resources": {}})
        niches = dict(eco.get("niches", {}))
        if niches.get("echo_cave", 0):
            niches["glowing_mycelium"] = min(8, niches.get("glowing_mycelium", 0) + 1)
            niches["echo_cave"] = max(0, niches["echo_cave"] - 1)
            if niches["echo_cave"] == 0:
                niches.pop("echo_cave", None)
            eco["niches"] = niches
            island.ecology = eco

    db.commit(); db.refresh(act)
    return {"id": act.id, "bond_id": act.bond_id, "actor_id": act.actor_id, "kind": act.kind}


# --- 付费订阅 / 情绪藏品 / 实体打印 -------------------------------------------

@app.post("/subscribe", response_model=schemas.EntitlementsResponse)
async def subscribe(request: schemas.SubscribeRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == request.user_id).first()
    if not user:
        # 演示切片：订阅时自动建档（真实鉴权不在本切片范围）
        user = models.User(id=request.user_id, username="guest_" + str(request.user_id), hashed_password="x")
        db.add(user)
    user.premium_tier = request.tier
    ent = dict(user.entitlements or {})
    ent["perception_toolkit"] = True  # 感知工具包：沉积钻取/生态图谱/气候预测
    ent["materials"] = list(request.materials)
    ent["ai_therapist"] = request.tier == "sanctuary"  # 不得将共情深度分级定价
    ent["double_island"] = request.tier in ("companion", "sanctuary")
    user.entitlements = ent
    user.is_premium = True
    db.commit()
    return {"user_id": user.id, "tier": user.premium_tier, "entitlements": user.entitlements}


@app.get("/entitlements/{user_id}", response_model=schemas.EntitlementsResponse)
async def get_entitlements(user_id: int, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": user.id, "tier": user.premium_tier, "entitlements": user.entitlements}


@app.post("/seed", response_model=schemas.SeedResponse)
async def create_seed(request: schemas.SeedRequest, db: Session = Depends(get_db)):
    island = db.query(models.MoodIsland).filter(models.MoodIsland.id == request.island_id).first()
    if not island:
        raise HTTPException(status_code=404, detail="Island not found")
    label = request.label or ("心境种子 · " + (island.visual_params or {}).get("mood", "neutral"))
    tree_svg = build_memorial_tree(island.visual_params or {})
    seed = models.MoodSeed(user_id=request.user_id, island_id=request.island_id, label=label, visual_params=island.visual_params, tree_svg=tree_svg, gifted_to=request.gift_to)
    db.add(seed); db.commit(); db.refresh(seed)
    return {"id": seed.id, "user_id": seed.user_id, "label": seed.label, "visual_params": seed.visual_params, "tree_svg": seed.tree_svg, "planted": seed.planted, "gifted_to": seed.gifted_to}


@app.post("/seed/{seed_id}/plant", response_model=schemas.SeedResponse)
async def plant_seed(seed_id: int, db: Session = Depends(get_db)):
    seed = db.query(models.MoodSeed).filter(models.MoodSeed.id == seed_id).first()
    if not seed:
        raise HTTPException(status_code=404, detail="Seed not found")
    seed.planted = True
    db.commit()
    return {"id": seed.id, "user_id": seed.user_id, "label": seed.label, "visual_params": seed.visual_params, "tree_svg": seed.tree_svg, "planted": seed.planted, "gifted_to": seed.gifted_to}


@app.get("/seeds/{user_id}")
async def list_seeds(user_id: int, db: Session = Depends(get_db)):
    seeds = db.query(models.MoodSeed).filter(
        (models.MoodSeed.user_id == user_id) | (models.MoodSeed.gifted_to == user_id)
    ).order_by(models.MoodSeed.id.desc()).all()
    return [{"id": s.id, "user_id": s.user_id, "label": s.label, "visual_params": s.visual_params, "tree_svg": s.tree_svg, "planted": s.planted, "gifted_to": s.gifted_to} for s in seeds]


@app.post("/print", response_model=schemas.PrintResponse)
async def create_print(request: schemas.PrintRequest, db: Session = Depends(get_db)):
    seed = db.query(models.MoodSeed).filter(models.MoodSeed.id == request.seed_id).first()
    if not seed:
        raise HTTPException(status_code=404, detail="Seed not found")
    order = models.PrintOrder(user_id=request.user_id, seed_id=request.seed_id, status="pending")
    db.add(order); db.commit(); db.refresh(order)
    return {"id": order.id, "seed_id": seed.id, "status": order.status, "tree_svg": seed.tree_svg}


@app.get("/prints/{user_id}")
async def list_prints(user_id: int, db: Session = Depends(get_db)):
    orders = db.query(models.PrintOrder).filter(models.PrintOrder.user_id == user_id).order_by(models.PrintOrder.id.desc()).all()
    return [{"id": o.id, "seed_id": o.seed_id, "status": o.status, "created_at": o.created_at} for o in orders]


@app.get("/mirror/{user_id}")
async def mirror(user_id: int, db: Session = Depends(get_db)):
    island = (
        db.query(models.MoodIsland)
        .filter(models.MoodIsland.user_id == user_id, models.MoodIsland.is_active.is_(True))
        .order_by(models.MoodIsland.id.desc()).first()
    )
    mood = (island.visual_params or {}).get("mood", "neutral") if island else "neutral"
    line = OBSERVER_LINES.get(mood, OBSERVER_LINES["neutral"])
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user and user.is_premium and (user.entitlements or {}).get("ai_therapist"):
        line = line + "\n它是不是，也在替你记着这一刻？"
    return {"mood": mood, "line": line}


# --- WebSocket 在场 ----------------------------------------------------------

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    await manager.connect(user_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            if message.get("type") == "presence":
                manager.set_presence(user_id, float(message.get("level", 0.0)))
            # 只向在场关系伙伴广播（投影光学浓度，不广播文字压力）
            db = SessionLocal()
            try:
                partners = _bond_partners(user_id, db)
            finally:
                db.close()
            await manager.broadcast(user_id, {
                "user_id": user_id,
                "type": message.get("type", "presence"),
                "data": message,
            }, partners=partners)
    except WebSocketDisconnect:
        manager.disconnect(user_id)


if __name__ == "__main__":
    import uvicorn
    # 绑定 0.0.0.0 以便真机/模拟器访问（局域网 IP 或 adb reverse）
    uvicorn.run(app, host="0.0.0.0", port=8000)
