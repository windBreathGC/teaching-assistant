"""教材分析服务：检查生成的教材Markdown是否符合规范，输出分析报告。

分析报告用于判断教材是否满足"一键更新"（解析+向量化）的要求。
"""
import logging
from pathlib import Path

from app.services.textbook_parser import parse_filename

logger = logging.getLogger(__name__)

# 分析阈值配置
MIN_CHAPTERS = 3          # 最少章节数
MIN_TOTAL_CHARS = 5000    # 最少总字数
MIN_CHAPTER_CHARS = 300   # 每章最少字数

# 学科特定的必要子内容检查
_REQUIRED_SUBSECTIONS = {
    "语文": ["课文全文", "重点字词", "课文结构", "主题思想"],
    "数学": ["例题", "习题", "公式", "定理"],
    "英语": ["词汇", "语法", "对话", "练习"],
    "科学": ["实验", "探究", "概念", "例题"],
    "社会": ["历史", "地理", "案例", "梳理"],
}


def analyze_textbook(file_path: str) -> dict:
    """分析教材Markdown文件，生成结构化分析报告。

    Args:
        file_path: 教材Markdown文件路径

    Returns:
        分析报告字典，包含结构检查、内容质量、改进建议等
    """
    path = Path(file_path)
    report: dict = {
        "filename": path.name,
        "structure_valid": False,
        "has_valid_filename": False,
        "has_title": False,
        "chapter_count": 0,
        "lesson_count": 0,
        "total_chars": 0,
        "avg_chars_per_chapter": 0,
        "has_failed_sections": False,
        "subject": None,
        "warnings": [],
        "recommendations": [],
        "detail": {},
        "ready_for_ingest": False,
    }

    if not path.exists():
        report["warnings"].append("文件不存在")
        return report

    # 1. 文件名检查
    filename_meta = parse_filename(path.name)
    if filename_meta:
        report["has_valid_filename"] = True
        report["subject"] = filename_meta["subject"]
    else:
        report["warnings"].append(
            "文件名格式不符合规范，应为: {版本}{年份}{年级}{学期}{学科}_{内容类型}.md"
        )

    # 2. 读取并解析内容
    content = path.read_text(encoding="utf-8")
    report["total_chars"] = len(content)
    lines = content.splitlines()

    # 3. 解析Markdown结构
    chapters: list[dict] = []
    current_chapter: dict | None = None
    has_title = False
    has_failed = False

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue

        level = 0
        for ch in stripped:
            if ch == "#":
                level += 1
            else:
                break

        title = stripped[level:].strip()

        if level == 1:
            has_title = True
        elif level == 2:
            current_chapter = {
                "title": title,
                "lessons": [],
                "char_count": 0,
                "subsections": [],
            }
            chapters.append(current_chapter)
        elif level == 3 and current_chapter is not None:
            current_chapter["lessons"].append({"title": title})
        elif level == 4 and current_chapter is not None:
            current_chapter["subsections"].append(title)

        # 检测生成失败的占位内容
        if "生成失败" in stripped or "错误：" in stripped:
            has_failed = True

    # 4. 统计字数（按章节估算：从当前章节标题到下一个章节标题之间的字符数）
    for i, ch in enumerate(chapters):
        start_idx = None
        end_idx = None
        for idx, line in enumerate(lines):
            if line.strip() == f"## {ch['title']}":
                start_idx = idx
            elif start_idx is not None and line.strip().startswith("## "):
                end_idx = idx
                break
        if start_idx is not None:
            if end_idx is None:
                end_idx = len(lines)
            ch["char_count"] = sum(len(line) for line in lines[start_idx:end_idx])

    report["has_title"] = has_title
    report["chapter_count"] = len(chapters)
    report["lesson_count"] = sum(len(ch["lessons"]) for ch in chapters)
    report["has_failed_sections"] = has_failed
    report["detail"]["chapters"] = [
        {
            "title": ch["title"],
            "lessons": len(ch["lessons"]),
            "char_count": ch["char_count"],
            "subsections": ch["subsections"][:10],
        }
        for ch in chapters
    ]

    if chapters:
        report["avg_chars_per_chapter"] = (
            sum(ch["char_count"] for ch in chapters) // len(chapters)
        )

    # 5. 结构验证与警告生成
    warnings = report["warnings"]
    recommendations = report["recommendations"]

    if not has_title:
        warnings.append("缺少 # 级别总标题")

    if len(chapters) < MIN_CHAPTERS:
        warnings.append(
            f"章节数过少（{len(chapters)}个），建议不少于{MIN_CHAPTERS}个"
        )

    empty_chapters = [
        ch["title"] for ch in chapters if ch["char_count"] < MIN_CHAPTER_CHARS
    ]
    if empty_chapters:
        warnings.append(
            f"以下章节内容过少（<{MIN_CHAPTER_CHARS}字）: {', '.join(empty_chapters[:3])}"
        )

    if has_failed:
        warnings.append("检测到生成失败的章节，需要重新生成或手动补充")

    # 学科特定检查
    subject = report["subject"]
    if subject and subject in _REQUIRED_SUBSECTIONS:
        required = _REQUIRED_SUBSECTIONS[subject]
        all_subsections = [s for ch in chapters for s in ch["subsections"]]
        matched = [r for r in required if any(r in s for s in all_subsections)]
        missing = [r for r in required if r not in matched]
        if missing:
            recommendations.append(
                f"建议补充以下{subject}学科常见内容板块: {', '.join(missing[:3])}"
            )

    # 6. 判断 ready_for_ingest
    ready = True
    if not report["has_valid_filename"]:
        ready = False
        recommendations.append("请修改文件名为标准格式，否则无法被扫描识别")
    if not report["has_title"]:
        ready = False
    if report["chapter_count"] < MIN_CHAPTERS:
        ready = False
    if report["total_chars"] < MIN_TOTAL_CHARS:
        ready = False
        recommendations.append(
            f"教材总字数不足（{report['total_chars']}字），建议补充至{MIN_TOTAL_CHARS}字以上"
        )
    if report["has_failed_sections"]:
        ready = False
        recommendations.append("存在生成失败的章节，请先修复后再执行向量化")

    report["ready_for_ingest"] = ready

    if ready:
        recommendations.append('教材结构完整，可以执行"一键全量更新"进行解析和向量化')
    else:
        recommendations.append("请根据上述警告修复问题后，再执行向量化操作")

    logger.info(
        "教材分析完成: %s, 章节=%d, 课程=%d, 字数=%d, ready=%s",
        path.name,
        report["chapter_count"],
        report["lesson_count"],
        report["total_chars"],
        ready,
    )
    return report
