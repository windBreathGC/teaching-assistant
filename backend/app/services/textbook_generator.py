"""教材自动生成服务：利用大模型根据参数自动采集/生成教材内容。

支持动态LLM配置（用户可指定 base_url、api_key、model_name），
生成符合项目规范的 Markdown 教材文件。
"""
import json
import logging
import re
from pathlib import Path
from typing import Callable

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from app.core.observability import observe, callback_config, flush_langfuse

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent.parent
TEXTBOOK_DIR = BASE_DIR / "textbook"

# ── 学科特定 Prompt 模板 ──

_OUTLINE_SYSTEM_PROMPT = """你是一位资深教材编辑，精通中国中学课程标准。请根据用户提供的教材信息，生成一份完整的教材大纲。

要求：
1. 大纲必须严格遵循对应学科的《义务教育课程标准》
2. 章节结构合理，符合该年级学生的认知水平
3. 语文/英语按"单元"组织，数学/科学按"章"组织，社会按"单元/专题"组织
4. 每个教学单元/章包含3-6个具体课程/课文/节
5. 输出必须为纯JSON，不要包含任何Markdown代码块标记

JSON格式：
{{
  "title": "教材总标题",
  "overview": "教材整体说明（100字左右）",
  "chapters": [
    {{
      "index": 1,
      "title": "第一单元：单元主题",
      "description": "单元主题说明（50字左右）",
      "lessons": [
        {{"index": 1, "title": "第1课 课文名称", "type": "教读|自读|写作|实验|专题"}}
      ]
    }}
  ]
}}"""

_OUTLINE_HUMAN_TEMPLATE = """请为以下教材生成完整大纲：

- 地区：{region}
- 学科：{subject}
- 年级：{grade}
- 学期：{semester}
- 出版社/版本：{publisher}
- 版本年份：{version_year}
- 特别说明：{notes}

请直接输出JSON，不要添加```json标记。"""

_CONTENT_SYSTEM_PROMPT = """你是一位优秀的中学教材编写专家。请根据提供的教材大纲和章节信息，编写完整的教材Markdown内容。

编写要求：
1. 内容必须准确、严谨，符合课程标准和教学大纲
2. 语文课文需包含：作者简介、创作背景、课文全文、重点字词注音、课文结构分析、主题思想
3. 数学章节需包含：概念引入、定理/公式、例题解析（2-3道）、课后习题
4. 英语单元需包含：词汇学习、语法要点、课文对话、练习题
5. 科学章节需包含：实验探究、概念讲解、例题、实践活动
6. 社会专题需包含：历史事件梳理、地理知识、案例分析
7. 使用标准Markdown格式，层级清晰
8. 内容要详实，每课不少于1500字

Markdown格式规范：
- # 级别：教材总标题（只出现一次）
- ## 级别：单元/章标题（如"第一单元：四季美景"）
- ### 级别：课程/课文标题（如"第1课 《春》/朱自清（教读）"）
- #### 级别：子内容（如"课文全文"、"重点字词"、"例题解析"）
- 表格用于词汇、公式等对照内容
- 列表用于结构分析、知识点梳理"""

_CONTENT_HUMAN_TEMPLATE = """请编写以下教材章节的完整内容：

教材信息：
- 标题：{title}
- 学科：{subject}
- 年级：{grade}{semester}
- 出版社：{publisher}

当前章节：
- 章节序号：{chapter_index}
- 章节标题：{chapter_title}
- 章节说明：{chapter_description}

本章节包含的课程：
{lessons_info}

{context_note}

请直接输出Markdown内容，从 ## 级别标题开始。"""


def _create_llm(model_config: dict) -> ChatOpenAI:
    """根据用户提供的配置创建LLM实例。"""
    return ChatOpenAI(
        model=model_config.get("model_name", "gpt-4o-mini"),
        api_key=model_config.get("api_key", ""),
        base_url=model_config.get("base_url", "https://api.openai.com/v1"),
        temperature=model_config.get("temperature", 0.3),
        max_tokens=4096,
    )


@observe(name="generate-outline")
def generate_outline(
    subject: str,
    grade: str,
    semester: str,
    publisher: str,
    version_year: str,
    region: str = "",
    notes: str = "",
    model_config: dict | None = None,
) -> dict:
    """生成教材大纲。

    Args:
        subject: 学科（语文/数学/英语/科学/社会）
        grade: 年级（七年级/八年级/九年级）
        semester: 学期（上册/下册）
        publisher: 出版社/版本（如部编版、浙教版、人教版）
        version_year: 版本年份（如2024）
        region: 适用地区
        notes: 特别说明
        model_config: LLM配置 {"base_url": str, "api_key": str, "model_name": str, "temperature": float}

    Returns:
        大纲字典，包含 title, overview, chapters[]
    """
    if model_config is None:
        raise ValueError("model_config 不能为空，必须提供LLM配置")

    logger.info("开始生成教材大纲: %s %s%s %s", publisher, grade, semester, subject)

    llm = _create_llm(model_config)
    prompt = ChatPromptTemplate.from_messages([
        ("system", _OUTLINE_SYSTEM_PROMPT),
        ("human", _OUTLINE_HUMAN_TEMPLATE),
    ])
    chain = prompt | llm | StrOutputParser()

    # 后台任务运行在独立线程，OTel 上下文不自动跨线程：显式挂 callback 让
    # LLM 调用嵌套进本函数的 observe span，形成一条完整 trace
    result = chain.invoke({
        "region": region or "全国通用",
        "subject": subject,
        "grade": grade,
        "semester": semester,
        "publisher": publisher,
        "version_year": version_year,
        "notes": notes or "无",
    }, config=callback_config(tags=["generate-outline", subject]))

    # 清理可能的代码块标记
    cleaned = re.sub(r"^```json\s*", "", result.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        outline = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error("大纲JSON解析失败: %s\n原始输出:\n%s", e, result)
        raise ValueError(f"大纲生成结果解析失败，请检查LLM输出格式: {e}") from e

    # 验证结构
    if "chapters" not in outline or not isinstance(outline["chapters"], list):
        raise ValueError("生成的大纲缺少 chapters 字段或格式不正确")

    logger.info("大纲生成完成: %d 个章节", len(outline["chapters"]))
    return outline


def _build_filename(publisher: str, year: str, grade: str, semester: str, subject: str) -> str:
    """构建符合规范的教材文件名。"""
    return f"{publisher}{year}{grade}{semester}{subject}_完整教材内容.md"


def _build_markdown_header(title: str, meta: dict) -> str:
    """构建教材Markdown文件头部。"""
    region = meta.get("region", "全国通用")
    publisher = meta.get("publisher", "")
    version_year = meta.get("version_year", "")
    grade = meta.get("grade", "")
    semester = meta.get("semester", "")
    subject = meta.get("subject", "")

    lines = [
        f"# {title}",
        "",
        f"> **适用地区**：{region}",
        f"> **出版社**：{publisher}",
        f"> **教材版本**：{version_year}年{semester}版",
        f"> **适用年级**：{grade}{semester}",
        f"> **学科**：{subject}",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


def _build_overview_section(overview: str, chapters: list[dict]) -> str:
    """构建教材整体结构概览。"""
    lines = [
        "## 教材整体结构",
        "",
        f"{overview}",
        "",
        "| 项目 | 内容 |",
        "|------|------|",
        f"| 单元/章数 | {len(chapters)}个 |",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


@observe(name="generate-textbook")
def generate_textbook(
    outline: dict,
    meta: dict,
    model_config: dict,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> Path:
    """基于大纲生成完整教材Markdown文件。

    Args:
        outline: 大纲字典（由 generate_outline 生成）
        meta: 教材元数据 {"subject", "grade", "semester", "publisher", "version_year", "region"}
        model_config: LLM配置
        progress_callback: 进度回调函数，接收 (current, total, message)

    Returns:
        生成的Markdown文件路径
    """
    if model_config is None:
        raise ValueError("model_config 不能为空")

    subject = meta["subject"]
    grade = meta["grade"]
    semester = meta["semester"]
    publisher = meta["publisher"]
    version_year = meta["version_year"]

    filename = _build_filename(publisher, version_year, grade, semester, subject)
    file_path = TEXTBOOK_DIR / filename

    # 如果文件已存在，添加序号避免覆盖
    counter = 1
    original_path = file_path
    while file_path.exists():
        stem = original_path.stem
        file_path = TEXTBOOK_DIR / f"{stem}_{counter}.md"
        counter += 1

    logger.info("开始生成教材: %s (%d 个章节)", filename, len(outline["chapters"]))

    # 构建文件头部
    md_parts = [_build_markdown_header(outline["title"], meta)]
    md_parts.append(_build_overview_section(outline.get("overview", ""), outline["chapters"]))

    llm = _create_llm(model_config)
    prompt = ChatPromptTemplate.from_messages([
        ("system", _CONTENT_SYSTEM_PROMPT),
        ("human", _CONTENT_HUMAN_TEMPLATE),
    ])
    chain = prompt | llm | StrOutputParser()

    total_chapters = len(outline["chapters"])

    for i, chapter in enumerate(outline["chapters"], start=1):
        if progress_callback:
            progress_callback(i, total_chapters, f"生成章节 {i}/{total_chapters}: {chapter['title']}")

        lessons_info = "\n".join(
            f"- 第{lesson['index']}课: {lesson['title']} ({lesson.get('type', '教读')})"
            for lesson in chapter.get("lessons", [])
        )

        # 添加上下文：如果前面章节已生成，简要提示连续性
        context_note = ""
        if i > 1:
            prev = outline["chapters"][i - 2]
            context_note = f"\n注意：前一章是「{prev['title']}」，请保持内容连贯性。"

        try:
            chapter_md = chain.invoke({
                "title": outline["title"],
                "subject": subject,
                "grade": grade,
                "semester": semester,
                "publisher": publisher,
                "chapter_index": chapter["index"],
                "chapter_title": chapter["title"],
                "chapter_description": chapter.get("description", ""),
                "lessons_info": lessons_info or "（本章为综合实践或复习章节）",
                "context_note": context_note,
            }, config=callback_config(tags=["generate-textbook", subject]))
        except Exception as e:
            logger.exception("章节生成失败: %s", chapter["title"])
            # 生成占位内容，不中断整体流程
            chapter_md = (
                f"## {chapter['title']}\n\n"
                f"> 本章内容生成失败，错误：{type(e).__name__}。"
                f"请手动补充或重新生成。\n\n"
            )

        md_parts.append(chapter_md)
        md_parts.append("\n---\n")

    # 写入文件
    full_content = "\n".join(md_parts)
    file_path.write_text(full_content, encoding="utf-8")

    # 本函数在 BackgroundTasks 线程中执行，结束前必须排空 Langfuse 上报队列
    flush_langfuse()

    logger.info("教材生成完成: %s (约 %d 字)", file_path, len(full_content))
    return file_path
