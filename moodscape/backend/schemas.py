from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime


class MoodParams(BaseModel):
    """A single island snapshot: the emotion archetype + its visual parameters."""
    mood: str
    palette: List[str]
    elements: str
    weather: str
    terrain: str
    particles: str
    energy: float
    valence: float
    tension: float
    clarity: float


class MoodRequest(BaseModel):
    text: str
    user_id: Optional[int] = None
    theme: Optional[str] = None  # premium render language (只改渲染, 不改情绪逻辑)


class MoodResponse(BaseModel):
    id: Optional[int] = None
    text: str
    visual_params: MoodParams
    ai_prompt: str
    evolution: Dict[str, Any] = {}
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ReleaseRequest(BaseModel):
    island_id: int
    emotion: str  # which negative emotion to release


class ReleaseResponse(BaseModel):
    island_id: int
    resource: str
    sediment_layer: Dict[str, Any]
    message: str


# --- 社交层 -------------------------------------------------------------

class BondRequest(BaseModel):
    user_a: int
    user_b: int


class BondResponse(BaseModel):
    id: int
    user_a: int
    user_b: int
    status: str


class BottleRequest(BaseModel):
    sender_id: int
    island_id: int
    ambience: str
    snippet: Dict[str, Any] = {}
    # 为空 = 真正的漂流，由任意一位陌生人拾取；指定 = 定向寄给某人
    recipient_id: Optional[int] = None


class BottleResponse(BaseModel):
    id: int
    sender_id: int
    ambience: str
    snippet: Dict[str, Any]
    created_at: Optional[datetime] = None


class ActionRequest(BaseModel):
    bond_id: int
    actor_id: int
    kind: str  # light | flower


class ActionResponse(BaseModel):
    id: int
    bond_id: int
    actor_id: int
    kind: str


# --- 付费订阅 -------------------------------------------------------------

class SubscribeRequest(BaseModel):
    user_id: int
    tier: str  # companion | sanctuary
    materials: List[str] = []


class EntitlementsResponse(BaseModel):
    user_id: int
    tier: str
    entitlements: Dict[str, Any]


class SeedRequest(BaseModel):
    user_id: int
    island_id: int
    label: Optional[str] = None
    gift_to: Optional[int] = None


class SeedResponse(BaseModel):
    id: int
    user_id: int
    label: str
    visual_params: Dict[str, Any]
    tree_svg: Optional[str] = None
    planted: bool
    gifted_to: Optional[int] = None


class PrintRequest(BaseModel):
    user_id: int
    seed_id: int


class PrintResponse(BaseModel):
    id: int
    seed_id: int
    status: str
    tree_svg: Optional[str] = None
