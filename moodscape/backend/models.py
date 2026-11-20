from sqlalchemy import Column, Integer, String, Float, JSON, DateTime, Boolean, ForeignKey
from sqlalchemy.sql import func
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_premium = Column(Boolean, default=False)
    premium_tier = Column(String, default="free")  # free | companion | sanctuary
    # 付费买工具/材质/仪式容器，不买"被倾听资格"或"关系质量"
    entitlements = Column(JSON, default={})  # {"perception_toolkit": true, "materials": [...], "ai_therapist": false, "double_island": false}
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MoodIsland(Base):
    """A persistent, evolving emotional island (长期数字资产)."""
    __tablename__ = "mood_islands"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    text_input = Column(String)

    visual_params = Column(JSON)
    evolution_stats = Column(JSON, default={})
    ecology = Column(JSON, default={})
    sediment_layers = Column(JSON, default=[])
    ai_prompt = Column(String)

    is_active = Column(Boolean, default=True)
    last_interacted = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# --- 社交层：静默陪伴 --------------------------------------------------------

class Bond(Base):
    """双岛 / 共栖空间：一份订阅双方共享；对方主动"回应"后桥才生成。"""
    __tablename__ = "bonds"

    id = Column(Integer, primary_key=True, index=True)
    user_a = Column(Integer, ForeignKey("users.id"))  # 发起方（出现桥墩）
    user_b = Column(Integer, ForeignKey("users.id"))  # 受邀方（必须本人回应）
    status = Column(String, default="pending")  # pending | active
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DriftBottle(Base):
    """漂流瓶 2.0：发送岛屿片段，对方进入微型景观并听到当时氛围音。"""
    __tablename__ = "drift_bottles"

    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"))
    island_id = Column(Integer, ForeignKey("mood_islands.id"))
    # 定向投放：指定收件人；为空则是真正的"漂流"，由单个陌生人拾取
    recipient_id = Column(Integer, nullable=True)
    snippet = Column(JSON)      # 岛屿片段 (visual_params)
    ambience = Column(String)   # 氛围音标识 (mood)
    opened_by = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    opened_at = Column(DateTime(timezone=True), nullable=True)


class IslandAction(Base):
    """低压互动：仅"点亮一盏灯""种下一朵花"，无文字回复压力。"""
    __tablename__ = "island_actions"

    id = Column(Integer, primary_key=True, index=True)
    bond_id = Column(Integer, ForeignKey("bonds.id"))
    actor_id = Column(Integer, ForeignKey("users.id"))
    kind = Column(String)  # light | flower
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# --- 情绪藏品 / 实体打印 ------------------------------------------------------

class MoodSeed(Base):
    """心境种子：将时刻封存，可种回岛、送人、随水土变异，长成纪念树。"""
    __tablename__ = "mood_seeds"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    island_id = Column(Integer, ForeignKey("mood_islands.id"))
    label = Column(String)
    visual_params = Column(JSON)
    tree_svg = Column(String, nullable=True)  # 纪念树形态 (printable)
    gifted_to = Column(Integer, nullable=True)
    planted = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PrintOrder(Base):
    """实体打印：纪念树形态打印订单。"""
    __tablename__ = "print_orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    seed_id = Column(Integer, ForeignKey("mood_seeds.id"))
    status = Column(String, default="pending")  # pending | printed | shipped
    created_at = Column(DateTime(timezone=True), server_default=func.now())
