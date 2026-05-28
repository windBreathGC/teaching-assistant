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

# 简化的章节映射（后续从知识库动态读取）
# 目前仅七年级上册有教材数据，其他年级待补充
_CHAPTERS_7A = {
    "chinese_7a": [
        ChapterInfo(id="c1", name="第一单元：四季美景", subject_id="chinese_7a"),
        ChapterInfo(id="c2", name="第二单元：至爱亲情", subject_id="chinese_7a"),
        ChapterInfo(id="c3", name="第三单元：学习生活", subject_id="chinese_7a"),
        ChapterInfo(id="c4", name="第四单元：人生之舟", subject_id="chinese_7a"),
        ChapterInfo(id="c5", name="第五单元：动物与人", subject_id="chinese_7a"),
        ChapterInfo(id="c6", name="第六单元：想象之翼", subject_id="chinese_7a"),
    ],
    "math_7a": [
        ChapterInfo(id="m1", name="第一章 有理数", subject_id="math_7a"),
        ChapterInfo(id="m2", name="第二章 有理数的运算", subject_id="math_7a"),
        ChapterInfo(id="m3", name="第三章 实数", subject_id="math_7a"),
        ChapterInfo(id="m4", name="第四章 代数式", subject_id="math_7a"),
        ChapterInfo(id="m5", name="第五章 一元一次方程", subject_id="math_7a"),
        ChapterInfo(id="m6", name="第六章 图形的初步知识", subject_id="math_7a"),
    ],
    "english_7a": [
        ChapterInfo(id="e_s1", name="Starter Unit 1", subject_id="english_7a"),
        ChapterInfo(id="e_s2", name="Starter Unit 2", subject_id="english_7a"),
        ChapterInfo(id="e_s3", name="Starter Unit 3", subject_id="english_7a"),
        ChapterInfo(id="e1", name="Unit 1", subject_id="english_7a"),
        ChapterInfo(id="e2", name="Unit 2", subject_id="english_7a"),
        ChapterInfo(id="e3", name="Unit 3", subject_id="english_7a"),
        ChapterInfo(id="e4", name="Unit 4", subject_id="english_7a"),
        ChapterInfo(id="e5", name="Unit 5", subject_id="english_7a"),
        ChapterInfo(id="e6", name="Unit 6", subject_id="english_7a"),
        ChapterInfo(id="e7", name="Unit 7", subject_id="english_7a"),
        ChapterInfo(id="e8", name="Unit 8", subject_id="english_7a"),
        ChapterInfo(id="e9", name="Unit 9", subject_id="english_7a"),
    ],
    "science_7a": [
        ChapterInfo(id="s1", name="第一章 科学入门", subject_id="science_7a"),
        ChapterInfo(id="s2", name="第二章 观察生物", subject_id="science_7a"),
        ChapterInfo(id="s3", name="第三章 人类的家园——地球", subject_id="science_7a"),
        ChapterInfo(id="s4", name="第四章 物质的特性", subject_id="science_7a"),
    ],
    "social_7a": [
        ChapterInfo(id="so1", name="第一单元：人在社会中生活", subject_id="social_7a"),
        ChapterInfo(id="so2", name="第二单元：人类共同生活的世界", subject_id="social_7a"),
        ChapterInfo(id="so3", name="第三单元：各具特色的区域生活", subject_id="social_7a"),
        ChapterInfo(id="so4", name="第四单元：不同类型的城市", subject_id="social_7a"),
        ChapterInfo(id="so5", name="第五单元：生活的变化", subject_id="social_7a"),
    ],
}

# 其他年级暂无教材数据，章节列表为空
_EMPTY_SUBJECT_IDS = [
    f"{sid}_{suffix}"
    for suffix in ["7b", "8a", "8b", "9a", "9b"]
    for sid, _, _, _, _ in _SUBJECTS_BASE
]
CHAPTERS = {**_CHAPTERS_7A, **{sid: [] for sid in _EMPTY_SUBJECT_IDS}}


LESSONS = {
    # 语文 - 部编版七年级上册
    "c1": [
        LessonInfo(id="c1_l1", name="春", chapter_id="c1", content_type="现代文"),
        LessonInfo(id="c1_l2", name="济南的冬天", chapter_id="c1", content_type="现代文"),
        LessonInfo(id="c1_l3", name="雨的四季", chapter_id="c1", content_type="现代文"),
        LessonInfo(id="c1_l4", name="古代诗歌四首", chapter_id="c1", content_type="古诗词"),
    ],
    "c2": [
        LessonInfo(id="c2_l1", name="秋天的怀念", chapter_id="c2", content_type="现代文"),
        LessonInfo(id="c2_l2", name="散步", chapter_id="c2", content_type="现代文"),
        LessonInfo(id="c2_l3", name="散文诗二首", chapter_id="c2", content_type="现代文"),
        LessonInfo(id="c2_l4", name="《世说新语》二则", chapter_id="c2", content_type="文言文"),
    ],
    "c3": [
        LessonInfo(id="c3_l1", name="从百草园到三味书屋", chapter_id="c3", content_type="现代文"),
        LessonInfo(id="c3_l2", name="再塑生命的人", chapter_id="c3", content_type="现代文"),
        LessonInfo(id="c3_l3", name="《论语》十二章", chapter_id="c3", content_type="文言文"),
        LessonInfo(id="c3_l4", name="写作：如何突出中心", chapter_id="c3", content_type="写作"),
        LessonInfo(id="c3_l5", name="名著导读：《朝花夕拾》", chapter_id="c3", content_type="名著"),
        LessonInfo(id="c3_poem", name="课外古诗词4首（一）", chapter_id="c3", content_type="古诗词"),
    ],
    "c4": [
        LessonInfo(id="c4_l1", name="纪念白求恩", chapter_id="c4", content_type="现代文"),
        LessonInfo(id="c4_l2", name="植树的牧羊人", chapter_id="c4", content_type="现代文"),
        LessonInfo(id="c4_l3", name="走一步，再走一步", chapter_id="c4", content_type="现代文"),
        LessonInfo(id="c4_l4", name="诫子书", chapter_id="c4", content_type="文言文"),
    ],
    "c5": [
        LessonInfo(id="c5_l1", name="猫", chapter_id="c5", content_type="现代文"),
        LessonInfo(id="c5_l2", name="动物笑谈", chapter_id="c5", content_type="现代文"),
        LessonInfo(id="c5_l3", name="狼", chapter_id="c5", content_type="文言文"),
    ],
    "c6": [
        LessonInfo(id="c6_l1", name="皇帝的新装", chapter_id="c6", content_type="现代文"),
        LessonInfo(id="c6_l2", name="天上的街市", chapter_id="c6", content_type="诗歌"),
        LessonInfo(id="c6_l3", name="女娲造人", chapter_id="c6", content_type="神话"),
        LessonInfo(id="c6_l4", name="寓言四则", chapter_id="c6", content_type="寓言"),
        LessonInfo(id="c6_poem", name="课外古诗词4首（二）", chapter_id="c6", content_type="古诗词"),
    ],
    # 数学 - 浙教版七年级上册
    "m1": [
        LessonInfo(id="m1_l1", name="1.1 从自然数到有理数", chapter_id="m1", content_type="新知"),
        LessonInfo(id="m1_l2", name="1.2 数轴", chapter_id="m1", content_type="新知"),
        LessonInfo(id="m1_l3", name="1.3 绝对值", chapter_id="m1", content_type="新知"),
        LessonInfo(id="m1_l4", name="1.4 有理数的大小比较", chapter_id="m1", content_type="新知"),
    ],
    "m2": [
        LessonInfo(id="m2_l1", name="2.1 有理数的加法", chapter_id="m2", content_type="新知"),
        LessonInfo(id="m2_l2", name="2.2 有理数的减法", chapter_id="m2", content_type="新知"),
        LessonInfo(id="m2_l3", name="2.3 有理数的乘法", chapter_id="m2", content_type="新知"),
        LessonInfo(id="m2_l4", name="2.4 有理数的除法", chapter_id="m2", content_type="新知"),
        LessonInfo(id="m2_l5", name="2.5 有理数的乘方", chapter_id="m2", content_type="新知"),
        LessonInfo(id="m2_l6", name="2.6 有理数的混合运算", chapter_id="m2", content_type="新知"),
        LessonInfo(id="m2_l7", name="2.7 近似数", chapter_id="m2", content_type="新知"),
    ],
    "m3": [
        LessonInfo(id="m3_l1", name="3.1 平方根", chapter_id="m3", content_type="新知"),
        LessonInfo(id="m3_l2", name="3.2 算术平方根", chapter_id="m3", content_type="新知"),
        LessonInfo(id="m3_l3", name="3.3 立方根", chapter_id="m3", content_type="新知"),
        LessonInfo(id="m3_l4", name="3.4 实数", chapter_id="m3", content_type="新知"),
    ],
    "m4": [
        LessonInfo(id="m4_l1", name="4.1 用字母表示数", chapter_id="m4", content_type="新知"),
        LessonInfo(id="m4_l2", name="4.2 代数式", chapter_id="m4", content_type="新知"),
        LessonInfo(id="m4_l3", name="4.3 整式", chapter_id="m4", content_type="新知"),
        LessonInfo(id="m4_l4", name="4.4 合并同类项", chapter_id="m4", content_type="新知"),
        LessonInfo(id="m4_l5", name="4.5 整式的加减", chapter_id="m4", content_type="新知"),
    ],
    "m5": [
        LessonInfo(id="m5_l1", name="5.1 一元一次方程", chapter_id="m5", content_type="新知"),
        LessonInfo(id="m5_l2", name="5.2 等式的基本性质", chapter_id="m5", content_type="新知"),
        LessonInfo(id="m5_l3", name="5.3 一元一次方程的解法", chapter_id="m5", content_type="新知"),
        LessonInfo(id="m5_l4", name="5.4 一元一次方程的应用", chapter_id="m5", content_type="应用"),
    ],
    "m6": [
        LessonInfo(id="m6_l1", name="6.1 几何图形", chapter_id="m6", content_type="新知"),
        LessonInfo(id="m6_l2", name="6.2 直线、射线、线段", chapter_id="m6", content_type="新知"),
        LessonInfo(id="m6_l3", name="6.3 角", chapter_id="m6", content_type="新知"),
        LessonInfo(id="m6_l4", name="6.4 余角和补角", chapter_id="m6", content_type="新知"),
        LessonInfo(id="m6_l5", name="6.5 直线的相交", chapter_id="m6", content_type="新知"),
    ],
    # 英语 - 人教PEP版七年级上册
    "e_s1": [
        LessonInfo(id="e_s1_l1", name="Section A", chapter_id="e_s1", content_type="听说"),
        LessonInfo(id="e_s1_l2", name="Self Check", chapter_id="e_s1", content_type="练习"),
    ],
    "e_s2": [
        LessonInfo(id="e_s2_l1", name="Section A", chapter_id="e_s2", content_type="听说"),
        LessonInfo(id="e_s2_l2", name="Self Check", chapter_id="e_s2", content_type="练习"),
    ],
    "e_s3": [
        LessonInfo(id="e_s3_l1", name="Section A", chapter_id="e_s3", content_type="听说"),
        LessonInfo(id="e_s3_l2", name="Self Check", chapter_id="e_s3", content_type="练习"),
    ],
    "e1": [
        LessonInfo(id="e1_l1", name="Section A", chapter_id="e1", content_type="听说"),
        LessonInfo(id="e1_l2", name="Section B", chapter_id="e1", content_type="读写"),
        LessonInfo(id="e1_l3", name="Self Check", chapter_id="e1", content_type="练习"),
    ],
    "e2": [
        LessonInfo(id="e2_l1", name="Section A", chapter_id="e2", content_type="听说"),
        LessonInfo(id="e2_l2", name="Section B", chapter_id="e2", content_type="读写"),
        LessonInfo(id="e2_l3", name="Self Check", chapter_id="e2", content_type="练习"),
    ],
    "e3": [
        LessonInfo(id="e3_l1", name="Section A", chapter_id="e3", content_type="听说"),
        LessonInfo(id="e3_l2", name="Section B", chapter_id="e3", content_type="读写"),
        LessonInfo(id="e3_l3", name="Self Check", chapter_id="e3", content_type="练习"),
    ],
    "e4": [
        LessonInfo(id="e4_l1", name="Section A", chapter_id="e4", content_type="听说"),
        LessonInfo(id="e4_l2", name="Section B", chapter_id="e4", content_type="读写"),
        LessonInfo(id="e4_l3", name="Self Check", chapter_id="e4", content_type="练习"),
    ],
    "e5": [
        LessonInfo(id="e5_l1", name="Section A", chapter_id="e5", content_type="听说"),
        LessonInfo(id="e5_l2", name="Section B", chapter_id="e5", content_type="读写"),
        LessonInfo(id="e5_l3", name="Self Check", chapter_id="e5", content_type="练习"),
    ],
    "e6": [
        LessonInfo(id="e6_l1", name="Section A", chapter_id="e6", content_type="听说"),
        LessonInfo(id="e6_l2", name="Section B", chapter_id="e6", content_type="读写"),
        LessonInfo(id="e6_l3", name="Self Check", chapter_id="e6", content_type="练习"),
    ],
    "e7": [
        LessonInfo(id="e7_l1", name="Section A", chapter_id="e7", content_type="听说"),
        LessonInfo(id="e7_l2", name="Section B", chapter_id="e7", content_type="读写"),
        LessonInfo(id="e7_l3", name="Self Check", chapter_id="e7", content_type="练习"),
    ],
    "e8": [
        LessonInfo(id="e8_l1", name="Section A", chapter_id="e8", content_type="听说"),
        LessonInfo(id="e8_l2", name="Section B", chapter_id="e8", content_type="读写"),
        LessonInfo(id="e8_l3", name="Self Check", chapter_id="e8", content_type="练习"),
    ],
    "e9": [
        LessonInfo(id="e9_l1", name="Section A", chapter_id="e9", content_type="听说"),
        LessonInfo(id="e9_l2", name="Section B", chapter_id="e9", content_type="读写"),
        LessonInfo(id="e9_l3", name="Self Check", chapter_id="e9", content_type="练习"),
    ],
    # 科学 - 浙教版七年级上册
    "s1": [
        LessonInfo(id="s1_l1", name="1.1 科学并不神秘", chapter_id="s1", content_type="探究"),
        LessonInfo(id="s1_l2", name="1.2 走进科学实验室", chapter_id="s1", content_type="探究"),
        LessonInfo(id="s1_l3", name="1.3 科学观察", chapter_id="s1", content_type="探究"),
        LessonInfo(id="s1_l4", name="1.4 科学测量", chapter_id="s1", content_type="探究"),
        LessonInfo(id="s1_l5", name="1.5 科学探究", chapter_id="s1", content_type="探究"),
    ],
    "s2": [
        LessonInfo(id="s2_l1", name="2.1 生物与非生物", chapter_id="s2", content_type="探究"),
        LessonInfo(id="s2_l2", name="2.2 细胞", chapter_id="s2", content_type="探究"),
        LessonInfo(id="s2_l3", name="2.3 生物体的结构层次", chapter_id="s2", content_type="探究"),
        LessonInfo(id="s2_l4", name="2.4 常见的动物", chapter_id="s2", content_type="探究"),
        LessonInfo(id="s2_l5", name="2.5 常见的植物", chapter_id="s2", content_type="探究"),
    ],
    "s3": [
        LessonInfo(id="s3_l1", name="3.1 地球的形状和内部结构", chapter_id="s3", content_type="探究"),
        LessonInfo(id="s3_l2", name="3.2 地球仪和地图", chapter_id="s3", content_type="探究"),
        LessonInfo(id="s3_l3", name="3.3 地球的运动", chapter_id="s3", content_type="探究"),
    ],
    "s4": [
        LessonInfo(id="s4_l1", name="4.1 物质的构成", chapter_id="s4", content_type="探究"),
        LessonInfo(id="s4_l2", name="4.2 质量的测量", chapter_id="s4", content_type="探究"),
        LessonInfo(id="s4_l3", name="4.3 物质的密度", chapter_id="s4", content_type="探究"),
        LessonInfo(id="s4_l4", name="4.4 物质的比热", chapter_id="s4", content_type="探究"),
        LessonInfo(id="s4_l5", name="4.5 熔化与凝固", chapter_id="s4", content_type="探究"),
        LessonInfo(id="s4_l6", name="4.6 汽化与液化", chapter_id="s4", content_type="探究"),
        LessonInfo(id="s4_l7", name="4.7 升华与凝华", chapter_id="s4", content_type="探究"),
    ],
    # 社会 - 人教版七年级上册
    "so1": [
        LessonInfo(id="so1_l1", name="第一课 我的家在哪里", chapter_id="so1", content_type="课文"),
        LessonInfo(id="so1_l2", name="第二课 在社会中成长", chapter_id="so1", content_type="课文"),
        LessonInfo(id="so1_l3", name="第三课 社会规则与秩序", chapter_id="so1", content_type="课文"),
    ],
    "so2": [
        LessonInfo(id="so2_l1", name="第四课 大洲和大洋", chapter_id="so2", content_type="课文"),
        LessonInfo(id="so2_l2", name="第五课 世界地形与气候", chapter_id="so2", content_type="课文"),
        LessonInfo(id="so2_l3", name="第六课 世界的人口与人种", chapter_id="so2", content_type="课文"),
        LessonInfo(id="so2_l4", name="第七课 世界的语言与宗教", chapter_id="so2", content_type="课文"),
        LessonInfo(id="so2_l5", name="第八课 世界的发展差异", chapter_id="so2", content_type="课文"),
    ],
    "so3": [
        LessonInfo(id="so3_l1", name="第九课 疆域与行政区划", chapter_id="so3", content_type="课文"),
        LessonInfo(id="so3_l2", name="第十课 自然环境", chapter_id="so3", content_type="课文"),
        LessonInfo(id="so3_l3", name="第十一课 自然资源", chapter_id="so3", content_type="课文"),
        LessonInfo(id="so3_l4", name="第十二课 人口与民族", chapter_id="so3", content_type="课文"),
    ],
    "so4": [
        LessonInfo(id="so4_l1", name="第十三课 北方地区", chapter_id="so4", content_type="课文"),
        LessonInfo(id="so4_l2", name="第十四课 南方地区", chapter_id="so4", content_type="课文"),
        LessonInfo(id="so4_l3", name="第十五课 西北地区", chapter_id="so4", content_type="课文"),
        LessonInfo(id="so4_l4", name="第十六课 青藏地区", chapter_id="so4", content_type="课文"),
    ],
    "so5": [
        LessonInfo(id="so5_l1", name="第十七课 认识区域", chapter_id="so5", content_type="课文"),
        LessonInfo(id="so5_l2", name="第十八课 区域发展", chapter_id="so5", content_type="课文"),
        LessonInfo(id="so5_l3", name="第十九课 区域联系", chapter_id="so5", content_type="课文"),
        LessonInfo(id="so5_l4", name="第二十课 走进家乡", chapter_id="so5", content_type="课文"),
    ],
}


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
