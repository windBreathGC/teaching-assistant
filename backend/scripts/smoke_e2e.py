# -*- coding: utf-8 -*-
"""端到端冒烟：多轮记忆 / 出题落库 / 判分 / 学情"""
import json
import urllib.request

BASE = "http://127.0.0.1:8123"


def post(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return req


def sse(path, payload):
    """消费 SSE 流，返回事件列表"""
    events = []
    with urllib.request.urlopen(post(path, payload), timeout=120) as resp:
        buf = b""
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n\n" in buf:
                raw, buf = buf.split(b"\n\n", 1)
                line = raw.decode("utf-8").strip()
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
    return events


def show(name, events):
    types = [e["type"] for e in events]
    done = next((e for e in events if e["type"] == "done"), {})
    print(f"\n=== {name} ===")
    print("事件序列:", types[:5], "..." if len(types) > 5 else "", f"(共{len(types)}个)")
    if done:
        print("reply 前80字:", (done.get("reply") or "")[:80].replace("\n", " "))
        print("references:", [r.get("lesson") for r in done.get("references", [])])
        print("retrieval_ok:", done.get("retrieval_ok"), "| session_id:", done.get("session_id", "")[:12])
        print("suggested:", done.get("suggested_actions"))
    return done


# 1) 第一轮：自由聊天
d1 = show("第1轮 自由聊天", sse("/chat/stream", {"message": "你好", "subject": "math_7a"}))
sid = d1.get("session_id")
assert sid, "缺少 session_id"

# 2) 第二轮：同会话知识问答（验证记忆 + references 事件）
d2 = show("第2轮 知识问答(同会话)", sse("/chat/stream", {
    "message": "什么是绝对值", "subject": "math_7a", "session_id": sid}))

# 3) 第三轮：指代消解（"它"指绝对值，验证多轮记忆）
d3 = show("第3轮 指代追问", sse("/chat/stream", {
    "message": "它有什么性质", "subject": "math_7a", "session_id": sid}))

# 4) 测验出题（验证 quiz_id 落库）
quiz_events = sse("/chat/quiz/stream", {
    "subject": "math_7a", "difficulty": "基础", "question_type": "选择"})
quiz_done = next((e for e in quiz_events if e["type"] == "done"), {})
print("\n=== 出题 ===")
print("题目:", (quiz_done.get("question") or "")[:60].replace("\n", " "))
print("quiz_id:", quiz_done.get("quiz_id"))
quiz_id = quiz_done.get("quiz_id")
assert quiz_id, "缺少 quiz_id"

# 5) 提交答案判分（故意答错，验证错因诊断）
correct = quiz_done.get("correct_answer", "A")
wrong = "B" if correct != "B" else "C"
req = post("/chat/quiz/submit", {"quiz_id": quiz_id, "user_answer": wrong})
with urllib.request.urlopen(req, timeout=120) as resp:
    grade = json.loads(resp.read().decode("utf-8"))
print("\n=== 判分（故意答错）===")
print("is_correct:", grade["is_correct"], "| misconception:", grade.get("misconception"))
print("diagnosis:", (grade.get("diagnosis") or "")[:80])
print("mastery:", grade.get("mastery"))

# 6) 幂等重复提交
req = post("/chat/quiz/submit", {"quiz_id": quiz_id, "user_answer": wrong})
with urllib.request.urlopen(req, timeout=120) as resp:
    grade2 = json.loads(resp.read().decode("utf-8"))
print("幂等重复提交: is_correct =", grade2["is_correct"],
      "| total_attempts =", (grade2.get("mastery") or {}).get("total_attempts"), "(应为1)")

# 7) 聊天内出题 → 作答判分闭环
d4 = show("第4轮 聊天内出题", sse("/chat/stream", {
    "message": "出道题考考我", "subject": "math_7a", "session_id": sid}))
d5 = show("第5轮 聊天内作答(我选A)", sse("/chat/stream", {
    "message": "我选A", "subject": "math_7a", "session_id": sid}))

# 8) 学情查询
d6 = show("第6轮 学情查询", sse("/chat/stream", {
    "message": "我的学习进度怎么样", "subject": "math_7a", "session_id": sid}))

print("\n全部冒烟完成")
