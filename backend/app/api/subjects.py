import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from app.models.schemas import SubjectInfo, ChapterInfo, LessonInfo

router = APIRouter(prefix="/subjects", tags=["subjects"])

_GRADE_SUFFIX = {
    "七年级上册": "7a",
    "七年级下册": "7b",
    "八年级上册": "8a",
    "八年级下册": "8b",
    "九年级上册": "9a",
    "九年级下册": "9b",
}

_SUBJECTS_BASE = [
    ("chinese", "语文", "部编版", "2024", "含课文、古诗词、名著导读"),
    ("math", "数学", "浙教版", "2024", "含章节内容、例题解析"),
    ("english", "英语", "人教PEP版", "2024", "含单元、词汇、语法"),
    ("science", "科学", "浙教版", "2024", "含章节、实验探究"),
    ("social", "社会", "人教版", "2024", "含历史与社会知识"),
]

_GRADES = [
    "七年级上册",
    "七年级下册",
    "八年级上册",
    "八年级下册",
    "九年级上册",
    "九年级下册",
]

SUBJECTS = [
    SubjectInfo(
        id=f"{sid}_{_GRADE_SUFFIX[grade]}",
        name=name,
        publisher=publisher,
        version=version,
        grade=grade,
        description=f"{publisher}{version}{grade}{name}，{desc}",
    )
    for grade in _GRADES
    for sid, name, publisher, version, desc in _SUBJECTS_BASE
]

# 从 JSON 配置文件加载章节和课程数据
_DATA_DIR = Path(Path(__file__).parent.parent.parent, "data", "subjects")


def _load_subject_chapters() -> dict[str, list[ChapterInfo]]:
    """加载所有有数据的学科的章节列表。"""
    chapters: dict[str, list[ChapterInfo]] = {}
    if not _DATA_DIR.exists():
        return chapters
    for json_file in _DATA_DIR.glob("*/*.json"):
        data = json.loads(json_file.read_text(encoding="utf-8"))
        subject_id = data.get("subject_id", "")
        if not subject_id:
            continue
        chapters[subject_id] = [
            ChapterInfo(id=ch["id"], name=ch["name"], subject_id=subject_id)
            for ch in data.get("chapters", [])
        ]
    return chapters


def _load_subject_lessons() -> dict[str, list[LessonInfo]]:
    """加载所有章节的课程列表。"""
    lessons: dict[str, list[LessonInfo]] = {}
    if not _DATA_DIR.exists():
        return lessons
    for json_file in _DATA_DIR.glob("*/*.json"):
        data = json.loads(json_file.read_text(encoding="utf-8"))
        for ch in data.get("chapters", []):
            chapter_id = ch["id"]
            lessons[chapter_id] = [
                LessonInfo(
                    id=ls["id"],
                    name=ls["name"],
                    chapter_id=chapter_id,
                    content_type=ls.get("content_type", ""),
                )
                for ls in ch.get("lessons", [])
            ]
    return lessons


_CHAPTERS_DATA = _load_subject_chapters()
_LESSONS_DATA = _load_subject_lessons()

# 尚未加载到教材数据的学科，章节列表为空
_LOADED_SUBJECT_IDS = set(_CHAPTERS_DATA.keys())
_EMPTY_SUBJECT_IDS = [
    f"{sid}_{suffix}"
    for suffix in ["7b", "8a", "8b", "9a", "9b"]
    for sid, _, _, _, _ in _SUBJECTS_BASE
    if f"{sid}_{suffix}" not in _LOADED_SUBJECT_IDS
]
CHAPTERS = {**_CHAPTERS_DATA, **{sid: [] for sid in _EMPTY_SUBJECT_IDS}}
LESSONS = _LESSONS_DATA


@router.get("", response_model=list[SubjectInfo])
async def list_subjects():
    return SUBJECTS


@router.get("/{subject_id}/chapters", response_model=list[ChapterInfo])
async def list_chapters(subject_id: str):
    return CHAPTERS.get(subject_id, [])


@router.get("/{subject_id}/chapters/{chapter_id}/lessons", response_model=list[LessonInfo])
async def list_lessons(subject_id: str, chapter_id: str):
    return LESSONS.get(chapter_id, [])


@router.get("/{subject_id}/lessons/{lesson_id}/content")
async def get_lesson_content(subject_id: str, lesson_id: str):
    """获取指定课文的原文内容"""
    from app.services.rag import get_lesson_name, get_doc_by_lesson_name
    lesson_name = get_lesson_name(lesson_id)
    if not lesson_name:
        raise HTTPException(status_code=404, detail="课文不存在")
    docs = get_doc_by_lesson_name(subject_id, lesson_name)
    if not docs:
        raise HTTPException(status_code=404, detail="课文内容未找到")
    return {
        "lesson_id": lesson_id,
        "lesson_name": lesson_name,
        "content": docs[0]["content"],
    }
