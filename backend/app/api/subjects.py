import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from app.models.schemas import SubjectInfo, ChapterInfo, LessonInfo

router = APIRouter(prefix="/subjects", tags=["subjects"])

_DATA_DIR = Path(__file__).parent.parent.parent / "data" / "subjects"


def _load_manifest() -> dict:
    """加载 manifest.json，返回学科基础配置。"""
    manifest_path = _DATA_DIR / "manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    return {"grade_suffix_map": {}, "grades": [], "subjects": []}


_MANIFEST = _load_manifest()
_GRADE_SUFFIX: dict[str, str] = _MANIFEST.get("grade_suffix_map", {})
_GRADES: list[str] = _MANIFEST.get("grades", [])
_SUBJECTS_BASE: list[dict] = _MANIFEST.get("subjects", [])

SUBJECTS = [
    SubjectInfo(
        id=f"{subj['id']}_{_GRADE_SUFFIX[grade]}",
        name=subj["name"],
        publisher=subj["publisher"],
        version=subj["version"],
        grade=grade,
        description=f"{subj['publisher']}{subj['version']}{grade}{subj['name']}，{subj.get('description', '')}",
    )
    for grade in _GRADES
    for subj in _SUBJECTS_BASE
]

# 从 JSON 配置文件加载章节和课程数据
# generated/ 目录存放自动解析的产物，优先于手工维护的 subjects/
_SUBJECTS_DIR = Path(Path(__file__).parent.parent.parent, "data", "subjects")
_GENERATED_DIR = Path(Path(__file__).parent.parent.parent, "data", "generated")


def _load_subject_chapters() -> dict[str, list[ChapterInfo]]:
    """加载所有有数据的学科的章节列表。
    优先使用 generated/ 目录的自动解析结果，fallback 到 subjects/ 手工数据。"""
    chapters: dict[str, list[ChapterInfo]] = {}
    for data_dir in (_SUBJECTS_DIR, _GENERATED_DIR):
        if not data_dir.exists():
            continue
        for json_file in data_dir.glob("*/*.json"):
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
    """加载所有章节的课程列表。
    优先使用 generated/ 目录的自动解析结果，fallback 到 subjects/ 手工数据。"""
    lessons: dict[str, list[LessonInfo]] = {}
    for data_dir in (_SUBJECTS_DIR, _GENERATED_DIR):
        if not data_dir.exists():
            continue
        for json_file in data_dir.glob("*/*.json"):
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
    f"{subj['id']}_{_GRADE_SUFFIX[grade]}"
    for grade in _GRADES
    for subj in _SUBJECTS_BASE
    if f"{subj['id']}_{_GRADE_SUFFIX[grade]}" not in _LOADED_SUBJECT_IDS
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
