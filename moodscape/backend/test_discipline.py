"""Moodscape 后端回归测试：覆盖交互纪律与生态规则。

用独立临时库运行，不触碰开发用 moodscape.db：
    cd moodscape/backend && .venv/bin/python test_discipline.py
"""

import os
import sys
import tempfile

# 必须在导入 main 之前设置，确保 engine 指向临时库
_tmp = tempfile.mkdtemp(prefix="moodscape-test-")
os.environ["MOODSCAPE_DB_URL"] = "sqlite:///" + os.path.join(_tmp, "test.db")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

client = TestClient(main.app)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  <- " + str(detail)) if detail and not cond else ""))


def user(uid, name):
    client.post("/users", json={"username": name, "password": "x"})
    return uid


print("\n[1] 情绪识别")
cases = {
    "最近压力好大，很焦虑": "anxious",
    "今天很平静，像水面一样放松": "calm",
    "一个人待着，好孤独": "lonely",
    "今天特别开心，很幸福": "happy",
    "我很难过，想哭": "sad",
}
for text, want in cases.items():
    r = client.post("/analyze", json={"user_id": 1, "text": text})
    got = r.json()["visual_params"]["mood"]
    check("'" + text[:10] + "...' -> " + want, got == want, "got " + got)

print("\n[1b] 否定与程度副词的边界")
# 程度副词内部的字不应被当作否定词（"特别"的"别"、"不"的远距离误套）
positive_cases = ["今天特别开心", "非常幸福", "太快乐了", "不想上班，但今天很开心"]
for text in positive_cases:
    r = client.post("/analyze", json={"user_id": 1, "text": text})
    vp = r.json()["visual_params"]
    check("'" + text + "' 效价为正", vp["valence"] > 0, vp["mood"] + "/" + str(vp["valence"]))

# 紧邻否定应生效
for text in ["我不开心", "没有一点快乐"]:
    r = client.post("/analyze", json={"user_id": 1, "text": text})
    vp = r.json()["visual_params"]
    check("'" + text + "' 效价为负", vp["valence"] < 0, vp["mood"] + "/" + str(vp["valence"]))

print("\n[2] 双岛：桥必须由受邀方本人回应")
r = client.post("/bond", json={"user_a": 1, "user_b": 2})
bond = r.json()
check("创建后为 pending（仅桥墩）", bond["status"] == "pending", bond)

r = client.get("/bond/" + str(bond["id"]) + "/bridge")
check("pending 阶段桥态为 pier", r.json()["bridge"] == "pier", r.json())

r = client.post("/bond/" + str(bond["id"]) + "/respond?user_id=1")
check("发起方代替对方回应 -> 403", r.status_code == 403, r.status_code)

r = client.post("/bond/" + str(bond["id"]) + "/respond?user_id=99")
check("无关者回应 -> 403", r.status_code == 403, r.status_code)

r = client.post("/bond/" + str(bond["id"]) + "/respond?user_id=2")
check("受邀方本人回应 -> active", r.status_code == 200 and r.json()["status"] == "active", r.json())

r = client.get("/bond/invites/2")
check("已回应后邀请列表清空", r.json() == [], r.json())

print("\n[3] 漂流瓶：收件人与单人拾取")
r = client.post("/bottle", json={"sender_id": 1, "island_id": 1, "ambience": "calm", "snippet": {"mood": "calm"}, "recipient_id": 2})
b_directed = r.json()["id"]
r = client.post("/bottle", json={"sender_id": 1, "island_id": 1, "ambience": "sad", "snippet": {"mood": "sad"}})
b_drift = r.json()["id"]

r = client.get("/bottle/1")
check("发送者看不到自己的瓶子", r.json() == [], r.json())

r = client.get("/bottle/3")
check("非收件人只看到漂流瓶（不含定向瓶）",
      len(r.json()) == 1 and r.json()[0]["id"] == b_drift, r.json())

r = client.get("/bottle/2")
check("收件人每次最多浮现一只", len(r.json()) == 1, r.json())

r = client.post("/bottle/" + str(b_directed) + "/open?user_id=3")
check("非收件人打开定向瓶 -> 403", r.status_code == 403, r.status_code)

r = client.post("/bottle/" + str(b_directed) + "/open?user_id=1")
check("打开自己的瓶子 -> 403", r.status_code == 403, r.status_code)

r = client.post("/bottle/" + str(b_directed) + "/open?user_id=2")
check("收件人打开成功", r.status_code == 200, r.status_code)

r = client.post("/bottle/" + str(b_drift) + "/open?user_id=3")
check("漂流瓶被 3 拾起", r.status_code == 200, r.status_code)
r = client.post("/bottle/" + str(b_drift) + "/open?user_id=4")
check("同一漂流瓶再被他人拾取 -> 409", r.status_code == 409, r.status_code)

print("\n[4] 生态位：上限与转化")
r = client.post("/analyze", json={"user_id": 7, "text": "很焦虑"})
iid = r.json()["id"]
for _ in range(30):
    client.post("/analyze", json={"user_id": 7, "text": "很焦虑，压力很大"})
eco = client.get("/island/7").json()["ecology"]["niches"]
check("晶体不无限增长（<=8）", eco.get("crystals", 0) <= 8, eco)
check("风蚀崖不无限增长（<=8）", eco.get("wind-eroded_cliff", 0) <= 8, eco)

before = client.get("/island/7").json()["ecology"]["niches"].get("crystals", 0)
client.post("/analyze", json={"user_id": 7, "text": "现在很平静，放松"})
after = client.get("/island/7").json()["ecology"]["niches"]
check("平静输入风化晶体为卵石苔藓",
      after.get("crystals", 0) < before and after.get("pebble_moss", 0) >= 1,
      {"before": before, "after": after})

print("\n[5] 连接感覆盖回声洞穴 -> 发光菌丝")
for _ in range(4):
    client.post("/analyze", json={"user_id": 8, "text": "一个人，好孤独"})
eco8 = client.get("/island/8").json()["ecology"]["niches"]
check("孤独形成回声洞穴", eco8.get("echo_cave", 0) >= 1, eco8)

r = client.post("/bond", json={"user_a": 9, "user_b": 8})
bond2 = r.json()["id"]
r = client.post("/action", json={"bond_id": bond2, "actor_id": 9, "kind": "light"})
check("桥未生成时陪伴动作 -> 409", r.status_code == 409, r.status_code)

client.post("/bond/" + str(bond2) + "/respond?user_id=8")
r = client.post("/action", json={"bond_id": bond2, "actor_id": 9, "kind": "light"})
check("桥生成后点灯成功", r.status_code == 200, r.status_code)
eco8b = client.get("/island/8").json()["ecology"]["niches"]
check("回声洞穴转为发光菌丝",
      eco8b.get("glowing_mycelium", 0) >= 1 and eco8b.get("echo_cave", 0) < eco8.get("echo_cave", 0),
      eco8b)

r = client.post("/action", json={"bond_id": bond2, "actor_id": 55, "kind": "light"})
check("非参与者的陪伴动作 -> 403", r.status_code == 403, r.status_code)

print("\n[6] 情绪清理：转化不删除")
layers_before = len(client.get("/island/7").json()["sediment_layers"])
r = client.post("/release", json={"island_id": iid, "emotion": "anxious"})
check("释放返回岛屿资源", r.status_code == 200 and "geothermal" in r.json()["resource"], r.json())
layers_after = client.get("/island/7").json()["sediment_layers"]
check("沉积层只增不减（未删除历史）", len(layers_after) == layers_before + 1,
      {"before": layers_before, "after": len(layers_after)})
check("释放层被标记 released", layers_after[-1].get("released") is True, layers_after[-1])

print("\n[7] 付费：不得将共情深度分级定价")
r = client.post("/subscribe", json={"user_id": 20, "tier": "companion", "materials": ["ghibli"]})
ent = r.json()["entitlements"]
check("同伴档位解锁双岛与材质", ent["double_island"] and ent["materials"] == ["ghibli"], ent)
check("感知工具包随订阅解锁", ent["perception_toolkit"] is True, ent)

print("\n[8] 观察者：只给环境线索，不超过两行")
r = client.get("/mirror/7")
line = r.json()["line"]
check("观察句不超过两行", len(line.split("\n")) <= 2, repr(line))
for word in ["你应该", "建议", "诊断", "抑郁症", "病"]:
    check("观察句不含诊断词 '" + word + "'", word not in line, repr(line))

print("\n" + "=" * 52)
print("通过 " + str(len(PASS)) + " 项，失败 " + str(len(FAIL)) + " 项")
if FAIL:
    print("失败项：")
    for f in FAIL:
        print("  - " + f)
print("=" * 52)
sys.exit(1 if FAIL else 0)
