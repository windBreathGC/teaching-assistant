from pydantic import BaseModel, Field
from typing import Literal, Optional


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
    description: Optional[str] = None


class LessonInfo(BaseModel):
    id: str
    name: str
    chapter_id: str
    content_type: Optional[str] = None


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    subject: Optional[str] = None
    chapter: Optional[str] = None
    lesson: Optional[str] = None
    history: list[dict] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str
    intent: Optional[str] = None
    references: list[dict] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)


class QuizRequest(BaseModel):
    subject: str
    chapter: Optional[str] = None
    lesson: Optional[str] = None
    difficulty: Literal["基础", "提高", "拓展"] = "基础"
    question_type: Literal["选择", "填空", "简答"] = "选择"


class QuizResponse(BaseModel):
    question: str
    options: Optional[list[str]] = None
    correct_answer: str
    explanation: str
    knowledge_point: str
