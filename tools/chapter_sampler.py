#!/usr/bin/env python3
"""
智能章节采样工具

支持三种采样策略：
- initial: 首轮采样前 N 章
- stratified: 分层采样（前/中/后各至少 1 章）
- uncertainty: 不确定性采样（分析 skill 中"原材料不足"标注，优先采样对应类型章节）

用法：
    python chapter_sampler.py --novel novel.txt --strategy initial --count 5
    python chapter_sampler.py --novel novel.txt --strategy stratified --count 5
    python chapter_sampler.py --novel novel.txt --strategy uncertainty --count 5 --skill-file writing.md
    python chapter_sampler.py --novel novel.txt --strategy stratified --count 5 --exclude 1,2,3,4,5
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

from novel_parser import detect_chapters, clean_text
from config import ENCODING_FALLBACK_ORDER


def read_file_with_fallback(path: Path) -> str:
    for encoding in ENCODING_FALLBACK_ORDER:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"无法以支持的编码读取文件：{path}")


def parse_novel_chapters(novel_path: Path) -> list[tuple[str, int, int, str]]:
    """
    解析小说文件，返回章节列表。

    Returns:
        list of (章节标题, 起始位置, 结束位置, 章节内容)
    """
    text = read_file_with_fallback(novel_path)
    text = clean_text(text)
    chapters = detect_chapters(text)

    result = []
    for i, (title, start, end) in enumerate(chapters):
        content = text[start:end].strip()
        result.append((title, start, end, content))

    return result


def initial_sample(
    chapters: list[tuple[str, int, int, str]],
    count: int = 5,
    exclude: Optional[set[int]] = None,
) -> list[int]:
    """
    首轮采样：取前 N 章。

    Args:
        chapters: 章节列表
        count: 采样章数
        exclude: 已采样章节索引集合（0-based）

    Returns:
        采样的章节索引列表（0-based）
    """
    exclude = exclude or set()
    sampled = []
    for i in range(min(count, len(chapters))):
        if i not in exclude:
            sampled.append(i)
    return sampled


def stratified_sample(
    chapters: list[tuple[str, int, int, str]],
    count: int = 5,
    exclude: Optional[set[int]] = None,
) -> list[int]:
    """
    分层采样：前/中/后各至少 1 章。

    将章节分为三段：前期(前1/3)、中期(中间1/3)、后期(后1/3)，
    每段至少采样1章，剩余名额均匀分配。

    Args:
        chapters: 章节列表
        count: 采样章数
        exclude: 已采样章节索引集合

    Returns:
        采样的章节索引列表
    """
    exclude = exclude or set()
    n = len(chapters)

    if n == 0:
        return []

    if n <= count:
        return [i for i in range(n) if i not in exclude]

    third = n // 3
    segments = [
        list(range(0, third)),
        list(range(third, 2 * third)),
        list(range(2 * third, n)),
    ]

    sampled = []

    for seg in segments:
        available = [i for i in seg if i not in exclude]
        if available:
            mid = len(available) // 2
            sampled.append(available[mid])

    remaining = count - len(sampled)
    if remaining > 0:
        all_available = [i for i in range(n) if i not in exclude and i not in sampled]
        per_seg = remaining // 3
        extra = remaining % 3

        for seg_idx, seg in enumerate(segments):
            available = [i for i in seg if i not in exclude and i not in sampled]
            seg_count = per_seg + (1 if seg_idx < extra else 0)
            step = max(1, len(available) // max(seg_count, 1))
            added = 0
            for j in range(0, len(available), step):
                if added >= seg_count:
                    break
                sampled.append(available[j])
                added += 1

    while len(sampled) < count:
        all_available = [i for i in range(n) if i not in exclude and i not in sampled]
        if not all_available:
            break
        sampled.append(all_available[len(all_available) // 2])

    return sorted(sampled)[:count]


def _classify_chapter(content: str) -> str:
    """
    简单的章节类型分类器。

    根据内容特征判断章节类型：
    - dialogue: 对话密集
    - action: 战斗/动作密集
    - emotion: 情感/心理密集
    - daily: 日常/铺垫
    - exposition: 设定/解说密集
    """
    dialogue_markers = re.findall(r'["\u201c\u201d"\u300c\u300d]', content)
    dialogue_ratio = len(dialogue_markers) / max(len(content), 1)

    action_keywords = r'(战斗|攻击|防御|闪避|出招|灵力|法术|剑气|拳风|杀意|对峙|冲锋|格挡|破防)'
    action_hits = len(re.findall(action_keywords, content))

    emotion_keywords = r'(心中一震|不禁|眼眶|泪水|心疼|愤怒|悲伤|温暖|感动|愧疚|释然|苦涩|心碎)'
    emotion_hits = len(re.findall(emotion_keywords, content))

    exposition_keywords = r'(修炼|等级|境界|功法|灵石|丹药|阵法|宗门|势力|规则|体系|传承)'
    exposition_hits = len(re.findall(exposition_keywords, content))

    if dialogue_ratio > 0.08:
        return "dialogue"
    if action_hits > 5:
        return "action"
    if emotion_hits > 3:
        return "emotion"
    if exposition_hits > 5:
        return "exposition"
    return "daily"


DIMENSION_TYPE_MAP = {
    "叙事风格": ["daily", "dialogue", "action"],
    "情节构建": ["action", "daily"],
    "人物塑造": ["dialogue", "emotion"],
    "世界观设定": ["exposition", "daily"],
    "对话风格": ["dialogue"],
    "描写风格": ["action", "emotion", "daily"],
    "表达风格": ["dialogue", "emotion"],
    "创作理念": ["dialogue", "emotion"],
    "互动行为": ["dialogue"],
}


def _find_uncertain_dimensions(skill_text: str) -> list[tuple[str, str]]:
    """
    从 skill 文本中找出标注了"原材料不足"的维度。

    Returns:
        list of (维度名, 建议的章节类型)
    """
    uncertain = []
    pattern = re.compile(r'原材料不足.*?建议追加(.*?)的章节', re.DOTALL)
    for match in pattern.finditer(skill_text):
        suggestion = match.group(1).strip()
        uncertain.append(("unknown", suggestion))

    section_pattern = re.compile(r'^#{2,3}\s+(.+?)$', re.MULTILINE)
    insufficient_pattern = re.compile(r'原材料不足|信息不足|暂无足够信息|建议追加', re.IGNORECASE)

    sections = list(section_pattern.finditer(skill_text))
    for i, match in enumerate(sections):
        section_name = match.group(1).strip()
        section_start = match.end()
        section_end = sections[i + 1].start() if i + 1 < len(sections) else len(skill_text)
        section_content = skill_text[section_start:section_end]

        if insufficient_pattern.search(section_content):
            for dim_name, types in DIMENSION_TYPE_MAP.items():
                if dim_name in section_name:
                    for t in types:
                        uncertain.append((dim_name, t))
                    break
            else:
                uncertain.append((section_name, "daily"))

    return uncertain


def uncertainty_sample(
    chapters: list[tuple[str, int, int, str]],
    skill_text: str,
    count: int = 5,
    exclude: Optional[set[int]] = None,
) -> list[int]:
    """
    不确定性采样：优先采样能填补 skill 空白的章节。

    分析 skill 中哪些维度最不确定（标注了"原材料不足"），
    优先采样对应类型的章节。

    Args:
        chapters: 章节列表
        skill_text: 当前 skill 文本（writing.md + author_persona.md）
        count: 采样章数
        exclude: 已采样章节索引集合

    Returns:
        采样的章节索引列表
    """
    exclude = exclude or set()
    n = len(chapters)

    if n == 0:
        return []

    uncertain_dims = _find_uncertain_dimensions(skill_text)
    preferred_types = set()
    for dim_name, chapter_type in uncertain_dims:
        preferred_types.add(chapter_type)

    if not preferred_types:
        return stratified_sample(chapters, count, exclude)

    chapter_types = {}
    for i, (title, start, end, content) in enumerate(chapters):
        if i not in exclude:
            chapter_types[i] = _classify_chapter(content)

    preferred_indices = [
        i for i, ctype in chapter_types.items()
        if ctype in preferred_types
    ]

    other_indices = [
        i for i, ctype in chapter_types.items()
        if ctype not in preferred_types
    ]

    sampled = []
    preferred_count = min(len(preferred_indices), max(count - 2, count // 2))
    remaining_count = count - preferred_count

    step_p = max(1, len(preferred_indices) // max(preferred_count, 1))
    for j in range(0, len(preferred_indices), step_p):
        if len(sampled) >= preferred_count:
            break
        sampled.append(preferred_indices[j])

    step_o = max(1, len(other_indices) // max(remaining_count, 1))
    for j in range(0, len(other_indices), step_o):
        if len(sampled) >= count:
            break
        sampled.append(other_indices[j])

    while len(sampled) < count:
        all_available = [i for i in range(n) if i not in exclude and i not in sampled]
        if not all_available:
            break
        sampled.append(all_available[len(all_available) // 2])

    return sorted(sampled)[:count]


def get_chapter_content(
    chapters: list[tuple[str, int, int, str]],
    indices: list[int],
) -> str:
    """
    根据索引列表获取章节内容，格式化输出。

    Args:
        chapters: 章节列表
        indices: 章节索引列表

    Returns:
        格式化的章节内容文本
    """
    parts = []
    for idx in indices:
        if idx < len(chapters):
            title, _, _, content = chapters[idx]
            parts.append(f"## {title}\n\n{content}")
    return "\n\n---\n\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description="智能章节采样工具")
    parser.add_argument("--novel", required=True, help="小说文件路径")
    parser.add_argument(
        "--strategy",
        required=True,
        choices=["initial", "stratified", "uncertainty"],
        help="采样策略",
    )
    parser.add_argument("--count", type=int, default=5, help="采样章数（默认：5）")
    parser.add_argument("--skill-file", help="skill 文件路径（uncertainty 策略需要）")
    parser.add_argument(
        "--exclude",
        help="已采样章节索引列表（逗号分隔，0-based），如 '0,1,2,3,4'",
    )
    parser.add_argument("--output", help="输出文件路径（不指定则输出到 stdout）")

    args = parser.parse_args()

    novel_path = Path(args.novel)
    if not novel_path.exists():
        print(f"错误：文件不存在 {novel_path}", file=sys.stderr)
        sys.exit(1)

    chapters = parse_novel_chapters(novel_path)
    if not chapters:
        print("错误：未识别到章节结构", file=sys.stderr)
        sys.exit(1)

    print(f"识别到 {len(chapters)} 章", file=sys.stderr)

    exclude = set()
    if args.exclude:
        try:
            exclude = {int(x.strip()) for x in args.exclude.split(",") if x.strip()}
        except ValueError:
            print("错误：--exclude 格式无效，应为逗号分隔的数字", file=sys.stderr)
            sys.exit(1)

    if args.strategy == "initial":
        sampled = initial_sample(chapters, args.count, exclude)
    elif args.strategy == "stratified":
        sampled = stratified_sample(chapters, args.count, exclude)
    elif args.strategy == "uncertainty":
        if not args.skill_file:
            print("错误：uncertainty 策略需要 --skill-file 参数", file=sys.stderr)
            sys.exit(1)

        skill_path = Path(args.skill_file)
        if not skill_path.exists():
            print(f"错误：skill 文件不存在 {skill_path}", file=sys.stderr)
            sys.exit(1)

        skill_text = skill_path.read_text(encoding="utf-8")
        sampled = uncertainty_sample(chapters, skill_text, args.count, exclude)
    else:
        print(f"错误：未知策略 {args.strategy}", file=sys.stderr)
        sys.exit(1)

    content = get_chapter_content(chapters, sampled)

    sampled_titles = [chapters[i][0] for i in sampled if i < len(chapters)]
    print(f"采样策略：{args.strategy}", file=sys.stderr)
    print(f"采样章节：{', '.join(sampled_titles)}", file=sys.stderr)
    print(f"采样索引：{', '.join(str(i) for i in sampled)}", file=sys.stderr)
    print(f"总字符数：{len(content)}", file=sys.stderr)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        print(f"输出已写入：{output_path}", file=sys.stderr)
    else:
        print(content)


if __name__ == "__main__":
    main()
