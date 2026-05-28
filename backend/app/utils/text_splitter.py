"""教材文本分块器"""
import re
from dataclasses import dataclass


@dataclass
class TextChunk:
    content: str
    metadata: dict


def split_by_headers(
    text: str, subject: str, publisher: str, grade: str = "", semester: str = ""
) -> list[TextChunk]:
    """按Markdown标题层级分块"""
    chunks = []
    chapter_pattern = re.compile(r'^##\s+(.+)$', re.MULTILINE)
    chapter_matches = list(chapter_pattern.finditer(text))

    for i, match in enumerate(chapter_matches):
        chapter_title = match.group(1).strip()
        start = match.start()
        end = chapter_matches[i + 1].start() if i + 1 < len(chapter_matches) else len(text)
        chapter_text = text[start:end]

        lesson_pattern = re.compile(r'^###\s+(.+)$', re.MULTILINE)
        lesson_matches = list(lesson_pattern.finditer(chapter_text))

        if lesson_matches:
            for j, lm in enumerate(lesson_matches):
                lesson_title = lm.group(1).strip()
                ls = lm.start()
                le = lesson_matches[j + 1].start() if j + 1 < len(lesson_matches) else len(chapter_text)
                lesson_text = chapter_text[ls:le]
                # 英语各单元的 Section A/B 名称重复，加章节前缀确保精确匹配
                lesson_meta = lesson_title
                if subject == "英语":
                    lesson_meta = f"{chapter_title} - {lesson_title}"
                chunks.append(TextChunk(
                    content=lesson_text.strip(),
                    metadata={
                        "subject": subject,
                        "publisher": publisher,
                        "grade": grade,
                        "semester": semester,
                        "chapter": chapter_title,
                        "lesson": lesson_meta,
                        "content_type": "课文内容",
                    }
                ))
        else:
            chunks.append(TextChunk(
                content=chapter_text.strip(),
                metadata={
                    "subject": subject,
                    "publisher": publisher,
                    "grade": grade,
                    "semester": semester,
                    "chapter": chapter_title,
                    "lesson": "",
                    "content_type": "章节概览",
                }
            ))
    return chunks


def load_and_split(
    file_path: str, subject: str, publisher: str, grade: str = "", semester: str = ""
) -> list[TextChunk]:
    with open(file_path, "r", encoding="utf-8") as f:
        text = f.read()
    return split_by_headers(text, subject, publisher, grade, semester)
