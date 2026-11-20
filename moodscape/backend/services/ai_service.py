"""
Moodscape Emotion Engine.

Translates free-form text (Chinese/English) into a continuous
VAD vector (valence / arousal-energy / tension) plus a clarity
measure, then maps it onto one of the five core mood archetypes
and their island visual parameters.

Design notes (per product spec):
- 焦虑 anxious -> grey-blue, fast electric clouds, jagged terrain
- 平静 calm    -> pale green, slow glowing jellyfish, rolling terrain
- 孤独 lonely  -> starry island, a single warm lantern
- 喜悦 happy   -> bright, blooming neon flowers, vibrant plateau
- 悲伤 sad     -> drizzle, wilting lilies, sunken basin
"""

from typing import Dict, Any, List, Tuple
import re


# AI 观察者克制在场：指向环境，不诊断心理，不超过两行
OBSERVER_LINES = {
    "anxious": "云压得很低，风在岛上走得很急。",
    "calm": "水母浮得很慢，连光都慢了下来。",
    "lonely": "岛上的那盏灯，一直亮着。",
    "happy": "花在开，光在轻轻跳。",
    "sad": "雨落在岛心，很轻很轻。",
    "neutral": "雾还没散。",
}


# ---------------------------------------------------------------------------
# Emotion lexicon: word -> (valence, arousal, tension)
#   valence in [-1, +1]  (negative -> positive)
#   arousal in [ 0,  1]  (calm -> energised)
#   tension in [ 0,  1]  (soft -> jagged / constricted)
# ---------------------------------------------------------------------------
LEXICON: Dict[str, Tuple[float, float, float]] = {
    # ---- anxious / 焦虑 ----
    "anxious": (-0.6, 0.75, 0.9), "anxiety": (-0.6, 0.75, 0.9),
    "worry": (-0.5, 0.6, 0.8), "worried": (-0.5, 0.6, 0.8),
    "nervous": (-0.5, 0.7, 0.85), "panic": (-0.8, 0.95, 1.0),
    "stress": (-0.6, 0.8, 0.9), "stressed": (-0.6, 0.8, 0.9),
    "焦虑": (-0.6, 0.75, 0.9), "不安": (-0.55, 0.7, 0.85),
    "紧张": (-0.5, 0.7, 0.85), "担心": (-0.5, 0.6, 0.8),
    "害怕": (-0.7, 0.8, 0.95), "恐慌": (-0.8, 0.95, 1.0),
    "压力": (-0.6, 0.8, 0.9), "烦躁": (-0.55, 0.75, 0.85),
    "心慌": (-0.6, 0.8, 0.9), "煎熬": (-0.6, 0.7, 0.85),

    # ---- calm / 平静 ----
    "calm": (0.7, 0.2, 0.15), "peaceful": (0.8, 0.15, 0.1),
    "peace": (0.8, 0.15, 0.1), "relaxed": (0.75, 0.2, 0.15),
    "relax": (0.75, 0.2, 0.15), "serene": (0.85, 0.15, 0.1),
    "tranquil": (0.8, 0.15, 0.1), "still": (0.6, 0.1, 0.15),
    "平静": (0.7, 0.2, 0.15), "安宁": (0.8, 0.15, 0.1),
    "安静": (0.6, 0.15, 0.15), "放松": (0.75, 0.2, 0.15),
    "平和": (0.8, 0.2, 0.1), "淡定": (0.6, 0.2, 0.15),
    "舒缓": (0.7, 0.15, 0.1), "惬意": (0.8, 0.25, 0.1),

    # ---- lonely / 孤独 ----
    "lonely": (-0.4, 0.15, 0.4), "loneliness": (-0.4, 0.15, 0.4),
    "alone": (-0.3, 0.15, 0.35), "isolated": (-0.5, 0.2, 0.45),
    "solitude": (-0.1, 0.1, 0.3), "empty": (-0.45, 0.15, 0.4),
    "孤独": (-0.4, 0.15, 0.4), "寂寞": (-0.4, 0.15, 0.4),
    "孤单": (-0.4, 0.15, 0.35), "一个人": (-0.3, 0.15, 0.35),
    "独处": (-0.1, 0.1, 0.3), "冷清": (-0.35, 0.1, 0.35),

    # ---- happy / 喜悦 ----
    "happy": (0.85, 0.8, 0.25), "joy": (0.9, 0.8, 0.2),
    "joyful": (0.9, 0.8, 0.2), "excited": (0.8, 0.95, 0.35),
    "glad": (0.75, 0.6, 0.2), "delighted": (0.9, 0.7, 0.2),
    "cheerful": (0.85, 0.7, 0.2), "wonderful": (0.9, 0.7, 0.2),
    "开心": (0.85, 0.8, 0.25), "高兴": (0.85, 0.75, 0.25),
    "快乐": (0.9, 0.8, 0.2), "喜悦": (0.9, 0.8, 0.2),
    "兴奋": (0.8, 0.95, 0.35), "幸福": (0.9, 0.6, 0.15),
    "愉快": (0.85, 0.7, 0.2), "满足": (0.8, 0.5, 0.15),

    # ---- sad / 悲伤 ----
    "sad": (-0.6, 0.2, 0.5), "sadness": (-0.6, 0.2, 0.5),
    "depressed": (-0.7, 0.15, 0.6), "unhappy": (-0.55, 0.2, 0.45),
    "grief": (-0.8, 0.2, 0.6), "cry": (-0.6, 0.3, 0.55),
    "sorrow": (-0.7, 0.2, 0.55), "hurt": (-0.6, 0.25, 0.5),
    "悲伤": (-0.6, 0.2, 0.5), "难过": (-0.6, 0.25, 0.5),
    "伤心": (-0.65, 0.25, 0.5), "低落": (-0.5, 0.15, 0.45),
    "沮丧": (-0.55, 0.15, 0.5), "忧郁": (-0.55, 0.15, 0.55),
    "委屈": (-0.55, 0.25, 0.5), "哭泣": (-0.6, 0.3, 0.55),
    "想哭": (-0.6, 0.3, 0.55), "难受": (-0.6, 0.3, 0.55),
    "痛苦": (-0.7, 0.3, 0.6), "疲惫": (-0.4, 0.1, 0.4),
}

NEGATORS = {"not", "no", "never", "don't", "dont", "不", "没有", "没", "不是", "无法", "难以", "毫无", "并不"}
INTENSIFIERS = {"very", "so", "really", "extremely", "absolutely", "很", "非常", "十分", "特别", "超级", "太", "极度"}
DIMINISHERS = {"a bit", "a little", "slightly", "somewhat", "有点", "稍微", "略", "一点点", "些许"}

# Archetypes -> visual parameters.
ARCHETYPES: Dict[str, Dict[str, Any]] = {
    "anxious": {
        "palette": ["#4A5568", "#2D3748", "#718096", "#5A6B85"],
        "elements": "jagged crystals, electric arcs, floating debris",
        "weather": "fast-moving storm clouds",
        "terrain": "jagged peaks",
        "particles": "sparks",
    },
    "calm": {
        "palette": ["#B2F5EA", "#81E6D9", "#C6F6D5", "#A8E6CF"],
        "elements": "glowing jellyfish, floating petals, soft ripples",
        "weather": "golden hour haze",
        "terrain": "rolling hills",
        "particles": "petals",
    },
    "lonely": {
        "palette": ["#1A202C", "#2D3748", "#4A5568", "#16213E"],
        "elements": "a single warm lantern, distant stars, mirror-like water",
        "weather": "clear starry night",
        "terrain": "small solitary mound",
        "particles": "stars",
    },
    "happy": {
        "palette": ["#FBD38D", "#F6AD55", "#FEEBC8", "#FDE68A"],
        "elements": "dancing light orbs, neon flowers, floating bubbles",
        "weather": "bright sun with rainbows",
        "terrain": "vibrant plateau",
        "particles": "bubbles",
    },
    "sad": {
        "palette": ["#A0AEC0", "#718096", "#4A5568", "#8B9CB0"],
        "elements": "falling rain, wilting lilies, deep puddles",
        "weather": "continuous drizzle",
        "terrain": "sunken basin",
        "particles": "rain",
    },
    "neutral": {
        "palette": ["#E2E8F0", "#CBD5E0", "#A0AEC0", "#D8DEE9"],
        "elements": "floating spheres, drifting mist",
        "weather": "neutral fog",
        "terrain": "flat plain",
        "particles": "mist",
    },
}

# Premium render languages (只改渲染语言, 不改情绪逻辑).
PREMIUM_THEMES: Dict[str, Dict[str, Any]] = {
    "cyberpunk": {
        "palette": ["#FF00FF", "#00FFFF", "#4B0082", "#0B0F19"],
        "elements": "neon grids, holographic shards, floating data streams",
        "weather": "digital acid rain",
        "terrain": "geometric obsidian spires",
        "particles": "glitch_bits",
    },
    "ghibli": {
        "palette": ["#A8E6CF", "#DCEDC1", "#FFD3B6", "#C6E9D8"],
        "elements": "fluffy clouds, ancient spirit trees, floating grass",
        "weather": "summer breeze",
        "terrain": "emerald meadows",
        "particles": "wind_whispers",
    },
    "deep-sea-ruins": {
        "palette": ["#0B3D5C", "#1B6B7A", "#2A9D8F", "#071B2B"],
        "elements": "sunken columns, bioluminescent vines, drifting ruins",
        "weather": "filtered deep light",
        "terrain": "submerged ruins",
        "particles": "bioluminescence",
    },
}


def _tokenize(text: str) -> List[str]:
    """Bilingual tokeniser: latin words, CJK bigrams, and CJK singletons."""
    tokens: List[str] = []
    tokens.extend(re.findall(r"[a-zA-Z']+", text.lower()))
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(run) == 1:
            tokens.append(run)
        else:
            for i in range(len(run) - 1):
                tokens.append(run[i:i + 2])
            tokens.append(run[-1])
    return tokens


class EmotionEngine:
    """Continuous emotion analysis from free text."""

    def analyze(self, text: str) -> Dict[str, Any]:
        tokens = _tokenize(text)
        raw = text.lower()

        weights: List[Tuple[float, Tuple[float, float, float]]] = []
        for tok in tokens:
            if tok in LEXICON:
                weights.append((1.0, LEXICON[tok]))

        # Catch short CJK emotion words embedded in longer runs.
        for word, v in LEXICON.items():
            if len(word) <= 2 and word in raw and word not in tokens:
                weights.append((0.8, v))

        if not weights:
            return self._params("neutral", 0.5, 0.5, 0.5, 0.5)

        intensity = 1.0
        for i in INTENSIFIERS:
            if i in raw:
                intensity = 1.25
                break
        for d in DIMINISHERS:
            if d in raw:
                intensity = 0.7
                break

        negated = self._is_negated(raw)

        total_w = sum(w for w, _ in weights) or 1.0
        valence = sum(w * v[0] for w, v in weights) / total_w
        arousal = sum(w * v[1] for w, v in weights) / total_w
        tension = sum(w * v[2] for w, v in weights) / total_w

        if negated:
            valence = -valence * 0.8

        valence = max(-1.0, min(1.0, valence))
        arousal = max(0.0, min(1.0, arousal * intensity))
        tension = max(0.0, min(1.0, tension * intensity))

        # clarity: high when calm & positive, low when tense/chaotic
        clarity = max(0.0, min(1.0, 1.0 - tension * 0.6 - max(0.0, arousal - 0.6) * 0.4))

        mood = self._classify(valence, arousal, tension)
        return self._params(mood, valence, arousal, tension, clarity)

    @staticmethod
    def _is_negated(raw: str) -> bool:
        """否定只在情绪词前方近距离生效。

        避免两类误判：
        - "特别开心" 里的 "别" 被当成否定词（已从词表移除）；
        - "不想上班，但今天很开心" 里远处的 "不" 反转了后面的情绪。
        """
        # 先屏蔽程度副词，防止其内部字符被当作否定词
        masked = raw
        for word in INTENSIFIERS | DIMINISHERS:
            if word in masked:
                masked = masked.replace(word, "　" * len(word))

        hits = []
        for neg in NEGATORS:
            start = 0
            while True:
                i = masked.find(neg, start)
                if i < 0:
                    break
                hits.append((i, len(neg)))
                start = i + 1
        if not hits:
            return False

        # 情绪词只要紧随某个否定词（4 字符窗口内）即视为被否定
        for word in LEXICON:
            j = masked.find(word)
            if j < 0:
                continue
            for i, n in hits:
                if 0 <= j - (i + n) <= 4:
                    return True
        return False

    def _classify(self, valence: float, arousal: float, tension: float) -> str:
        centres = {
            "anxious": (-0.6, 0.75, 0.9),
            "calm": (0.7, 0.2, 0.15),
            "lonely": (-0.4, 0.15, 0.4),
            "happy": (0.85, 0.8, 0.25),
            "sad": (-0.6, 0.2, 0.5),
        }
        best, best_d = "neutral", float("inf")
        for mood, (cv, ca, ct) in centres.items():
            d = (valence - cv) ** 2 + (arousal - ca) ** 2 + (tension - ct) ** 2
            if d < best_d:
                best_d, best = d, mood
        return best

    def _params(self, mood: str, valence: float, arousal: float, tension: float, clarity: float) -> Dict[str, Any]:
        arch = ARCHETYPES[mood]
        return {
            "mood": mood,
            "palette": list(arch["palette"]),
            "elements": arch["elements"],
            "weather": arch["weather"],
            "terrain": arch["terrain"],
            "particles": arch["particles"],
            "energy": round(arousal, 3),
            "valence": round(valence, 3),
            "tension": round(tension, 3),
            "clarity": round(clarity, 3),
        }

    def from_vad(self, valence: float, arousal: float, tension: float) -> Dict[str, Any]:
        """Build island params directly from a VAD vector (used by audio/song input)."""
        valence = max(-1.0, min(1.0, valence))
        arousal = max(0.0, min(1.0, arousal))
        tension = max(0.0, min(1.0, tension))
        clarity = max(0.0, min(1.0, 1.0 - tension * 0.6 - max(0.0, arousal - 0.6) * 0.4))
        mood = self._classify(valence, arousal, tension)
        return self._params(mood, valence, arousal, tension, clarity)


class AIService:
    """Public service facade used by the API layer."""

    def __init__(self):
        self.engine = EmotionEngine()

    def analyze_emotion(self, text: str, is_premium: bool = False, theme_pref: str = None) -> Dict[str, Any]:
        params = self.engine.analyze(text)
        if is_premium and theme_pref in PREMIUM_THEMES:
            params = {**params, **PREMIUM_THEMES[theme_pref]}
        return params

    def generate_ai_prompt(self, params: Dict[str, Any]) -> str:
        return (
            "A cinematic, surreal 3D floating island in a void. "
            "Terrain: " + params["terrain"] + ". Atmosphere: " + params["weather"] + ". "
            "Key elements: " + params["elements"] + ". "
            "Color palette: " + ", ".join(params["palette"]) + ". "
            "Hyper-realistic, 8k, Octane Render, whimsical, emotional atmosphere, volumetric lighting."
        )


# Backwards-compatible alias
MoodscapeEngine = EmotionEngine
