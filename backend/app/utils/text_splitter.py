"""教材文本分块器"""
import re
from dataclasses import dataclass
from app.core.config import get_settings

settings = get_settings()

@dataclass
class TextChunk:
    content: str
    metadata: dict


def _split_long_text(text: str, max_chars: int = settings.MAX_CHUNK_CHARS) -> list[str]:
    """按行将超长文本贪心切分为不超过 max_chars 的片段；单行仍超长则硬切。"""
    if len(text) <= max_chars:
        return [text]

    parts: list[str] = []
    buf = ""
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        while len(line) > max_chars:
            if buf:
                parts.append(buf)
                buf = ""
            parts.append(line[:max_chars])
            line = line[max_chars:].strip()
        if not line:
            continue
        candidate = f"{buf}\n{line}" if buf else line
        if len(candidate) > max_chars:
            parts.append(buf)
            buf = line
        else:
            buf = candidate
    if buf:
        parts.append(buf)
    return parts


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

    # 对超长块做二次切分，避免超出 Embedding 模型的 token 上限
    result: list[TextChunk] = []
    for chunk in chunks:
        if len(chunk.content) <= settings.MAX_CHUNK_CHARS:
            result.append(chunk)
        else:
            for part in _split_long_text(chunk.content):
                result.append(TextChunk(content=part, metadata=chunk.metadata))
    return result


def load_and_split(
    file_path: str, subject: str, publisher: str, grade: str = "", semester: str = ""
) -> list[TextChunk]:
    with open(file_path, "r", encoding="utf-8") as f:
        text = f.read()
    return split_by_headers(text, subject, publisher, grade, semester)
