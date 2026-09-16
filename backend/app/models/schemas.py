from pydantic import BaseModel, Field
from typing import Literal


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"


class SubjectInfo(BaseModel):
    id: str
    name: str
    publisher: str
    version: str
    grade: str
    description: str


class ChapterInfo(BaseModel):
    id: str
    name: str
    subject_id: str
    description: str | None = None


class LessonInfo(BaseModel):
    id: str
    name: str
    chapter_id: str
    content_type: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    subject: str | None = None
    chapter: str | None = None
    lesson: str | None = None
    session_id: str | None = None  # 会话ID：服务端按它持久化多轮记忆，为空则新建
    # 兼容字段：旧前端显式回传历史；checkpointer 记忆上线后服务端不再消费它
    history: list[dict] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str
    intent: str | None = None
    session_id: str | None = None
    references: list[dict] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)


class QuizRequest(BaseModel):
    subject: str
    chapter: str | None = None
    lesson: str | None = None
    difficulty: Literal["基础", "提高", "拓展"] = "基础"
    question_type: Literal["选择", "填空", "简答"] = "选择"


class QuizResponse(BaseModel):
    question: str
    options: list[str] | None = None
    correct_answer: str
    explanation: str
    knowledge_point: str
    quiz_id: str | None = None  # 出题落库ID，提交答案判分时凭它关联


class QuizSubmitRequest(BaseModel):
    quiz_id: str = Field(..., min_length=1, max_length=64)
    user_answer: str = Field(..., min_length=1, max_length=2000)


class QuizGradeResponse(BaseModel):
    quiz_id: str
    is_correct: bool
    correct_answer: str
    explanation: str
    diagnosis: str = ""
    misconception: str | None = None
    knowledge_point: str
    mastery: dict | None = None  # {knowledge_point, mastery, total_attempts, correct_attempts}
