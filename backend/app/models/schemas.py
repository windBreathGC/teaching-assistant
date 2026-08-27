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
    history: list[dict] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str
    intent: str | None = None
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
