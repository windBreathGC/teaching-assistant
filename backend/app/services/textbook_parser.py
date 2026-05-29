"""教材Markdown解析服务：从教材文件自动提取章节结构，生成metadata.json。

解析规则：
- 文件名 -> 版本、年份、年级、学期、学科
- ## -> 章节（chapter）
- ### -> 课程（lesson）
- #### -> 子内容（向量化时合并到上级课程，不单独生成课程ID）
"""
import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# 文件名解析正则（与 ingest_textbooks.py 保持一致）
FILENAME_PATTERN = re.compile(
    r"^(?P<version>[^0-9]+)"
    r"(?P<year>\d{4})"
    r"(?P<grade>七年级|八年级|九年级|高一|高二|高三)"
    r"(?P<semester>上册|下册)"
    r"(?P<subject>语文|数学|英语|科学|社会)"
    r"_(?P<content_type>.+)\.md$"
)

# 年级 -> 后缀映射
GRADE_SUFFIX_MAP = {
    "七年级上册": "7a",
    "七年级下册": "7b",
    "八年级上册": "8a",
    "八年级下册": "8b",
    "九年级上册": "9a",
    "九年级下册": "9b",
}

# 学科 -> 前缀映射
SUBJECT_PREFIX_MAP = {
    "语文": "c",
    "数学": "m",
    "英语": "e",
    "科学": "s",
    "社会": "so",
}

# 学科 -> ID映射
SUBJECT_ID_MAP = {
    "语文": "chinese",
    "数学": "math",
    "英语": "english",
    "科学": "science",
    "社会": "social",
}


def parse_filename(filename: str) -> dict | None:
    """从文件名解析教材元数据。"""
    m = FILENAME_PATTERN.match(filename)
    if not m:
        return None
    return {
        "version": m.group("version"),
        "year": m.group("year"),
        "grade": m.group("grade"),
        "semester": m.group("semester"),
        "subject": m.group("subject"),
        "content_type": m.group("content_type"),
    }


def _make_chapter_id(grade_suffix: str, subject_prefix: str, chapter_index: int) -> str:
    """生成章节ID，如 7b_c1。"""
    return f"{grade_suffix}_{subject_prefix}{chapter_index}"


def _make_lesson_id(chapter_id: str, lesson_index: int) -> str:
    """生成课程ID，如 7b_c1_l1。"""
    return f"{chapter_id}_l{lesson_index}"


def _detect_content_type(lesson_title: str) -> str:
    """根据课程标题自动检测内容类型。"""
    title = lesson_title.lower()
    if "写作" in title or "作文" in title:
        return "写作"
    if "古诗词" in title or "古诗" in title or "诗" in title:
        return "古诗词"
    if "文言文" in title:
        return "文言文"
    if "名著" in title:
        return "名著"
    if "自读" in title or "*" in lesson_title:
        return "自读"
    if "现代文" in title:
        return "现代文"
    if "诗歌" in title:
        return "诗歌"
    if "寓言" in title:
        return "寓言"
    if "神话" in title:
        return "神话"
    if "专题" in title or "活动" in title:
        return "专题"
    if "整本书" in title:
        return "整本书阅读"
    if "实验" in title or "探究" in title:
        return "实验"
    if "复习" in title or "总结" in title:
        return "复习"
    return "现代文"


def parse_markdown_structure(file_path: str) -> dict:
    """解析Markdown文件，提取章节和课程结构。

    返回标准metadata字典，格式与现有JSON兼容。
    """
    path = Path(file_path)
    meta = parse_filename(path.name)
    if not meta:
        raise ValueError(f"文件名格式不匹配: {path.name}")

    grade_full = meta["grade"] + meta["semester"]
    grade_suffix = GRADE_SUFFIX_MAP.get(grade_full, "")
    subject_prefix = SUBJECT_PREFIX_MAP.get(meta["subject"], "")
    subject_id = SUBJECT_ID_MAP.get(meta["subject"], "")

    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()

    chapters: list[dict] = []
    current_chapter: dict | None = None
    chapter_index = 0
    lesson_index = 0

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("##"):
            continue

        # 计算标题层级
        level = 0
        for ch in stripped:
            if ch == "#":
                level += 1
            else:
                break

        title = stripped[level:].strip()

        # 跳过文件总标题和特殊表格
        if level == 1:
            continue

        if level == 2:
            # 跳过非章节标题
            skip_keywords = ("整体结构", "目录", "附录", "参考", "说明")
            if any(k in title for k in skip_keywords):
                continue
            # 新章节
            chapter_index += 1
            lesson_index = 0
            chapter_id = _make_chapter_id(grade_suffix, subject_prefix, chapter_index)
            current_chapter = {
                "id": chapter_id,
                "name": title,
                "lessons": [],
            }
            chapters.append(current_chapter)

        elif level == 3 and current_chapter is not None:
            # 新课程
            lesson_index += 1
            lesson_id = _make_lesson_id(current_chapter["id"], lesson_index)
            content_type = _detect_content_type(title)
            current_chapter["lessons"].append({
                "id": lesson_id,
                "name": title,
                "content_type": content_type,
            })

        # level == 4 是子内容，不生成独立课程ID

    return {
        "subject_id": f"{subject_id}_{grade_suffix}",
        "subject_name": meta["subject"],
        "grade": grade_full,
        "publisher": meta["version"],
        "version": meta["year"],
        "description": _make_description(meta),
        "chapters": chapters,
    }


def _make_description(meta: dict) -> str:
    """根据学科生成描述。"""
    subject = meta["subject"]
    descriptions = {
        "语文": "含课文、古诗词、名著导读",
        "数学": "含章节内容、例题解析",
        "英语": "含单元、词汇、语法",
        "科学": "含章节、实验探究",
        "社会": "含历史与社会知识",
    }
    return descriptions.get(subject, "")


def generate_metadata(file_path: str, output_dir: str | None = None) -> Path:
    """解析教材并生成metadata.json文件。

    Args:
        file_path: 教材Markdown文件路径
        output_dir: 输出目录，默认 backend/data/generated/

    Returns:
        生成的JSON文件路径
    """
    path = Path(file_path)
    meta = parse_filename(path.name)
    if not meta:
        raise ValueError(f"无法解析文件名: {path.name}")

    data = parse_markdown_structure(file_path)

    grade_full = meta["grade"] + meta["semester"]
    grade_suffix = GRADE_SUFFIX_MAP.get(grade_full, "")
    subject_id = SUBJECT_ID_MAP.get(meta["subject"], meta["subject"])

    if output_dir is None:
        base = Path(path).parent.parent.parent / "backend" / "data" / "generated"
    else:
        base = Path(output_dir)

    out_dir = base / grade_suffix
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"{subject_id}.json"
    out_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("已生成 metadata: %s (章节数=%d)", out_path, len(data["chapters"]))
    return out_path


def scan_textbooks(textbook_dir: str) -> list[dict]:
    """扫描教材目录，返回所有可解析的教材文件信息。

    Returns:
        每个教材文件的字典列表，包含 filename, meta, status
    """
    dir_path = Path(textbook_dir)
    results = []
    if not dir_path.exists():
        return results

    for file_path in sorted(dir_path.glob("*.md")):
        if file_path.name.startswith("TEMPLATE"):
            continue
        meta = parse_filename(file_path.name)
        if meta:
            results.append({
                "filename": file_path.name,
                "path": str(file_path),
                "meta": meta,
            })
    return results
