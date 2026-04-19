#!/usr/bin/env python3
"""
网文作者蒸馏编排器

将解析器输出、分析 Prompt、生成模板串联为完整的蒸馏流程。

用法：
    python distill.py --slug feitianyu --name "飞天鱼" \\
        --novels novel1.txt novel2.epub \\
        --comments comments.txt --platform 起点 \\
        --social weibo.txt \\
        --mode sample \\
        --base-dir ./authors
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from novel_parser import parse_novel
from epub_parser import parse_epub, extract_metadata
from comment_parser import (
    parse_qidian_comments,
    parse_jinjiang_comments,
    parse_fanqie_comments,
    parse_json_comments,
)
from wechat_parser import parse_wechat_html, parse_wechat_text, is_html_content
from weibo_collector import parse_weibo_text, parse_weibo_json, normalize_weibo
from skill_writer import create_skill, slugify, validate_slug
from config import ENCODING_FALLBACK_ORDER

MAX_PROMPT_CHARS = 200_000


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def read_file_with_fallback(path: Path) -> str:
    """尝试多种编码读取文件，按 ENCODING_FALLBACK_ORDER 顺序回退"""
    for encoding in ENCODING_FALLBACK_ORDER:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"无法以支持的编码读取文件：{path}")


# ---------------------------------------------------------------------------
# 原材料收集
# ---------------------------------------------------------------------------

def select_representative_chapters(text: str, max_chars: int = MAX_PROMPT_CHARS) -> str:
    """从解析后的小说文本中选取代表性章节，控制总字符数

    策略：
    1. 始终保留前 3 章（建立风格）
    2. 均匀间隔选取中间章节
    3. 始终保留最后 3 章（收尾风格）
    4. 总字符数不超过 max_chars
    """
    chapters = re.split(r'(?=^## )', text, flags=re.MULTILINE)
    chapters = [c for c in chapters if c.strip().startswith('## ')]

    if not chapters:
        return text[:max_chars]

    total_chars = sum(len(c) for c in chapters)
    if total_chars <= max_chars:
        return text[:max_chars]

    n = len(chapters)
    head_count = min(3, n)
    tail_count = min(3, max(n - head_count, 0))

    head_chapters = chapters[:head_count]
    tail_chapters = chapters[-tail_count:] if tail_count > 0 else []

    head_chars = sum(len(c) for c in head_chapters)
    tail_chars = sum(len(c) for c in tail_chapters)
    remaining_budget = max_chars - head_chars - tail_chars

    if remaining_budget <= 0:
        result = "\n".join(head_chapters)
        if len(result) < max_chars and tail_chapters:
            result += "\n" + "\n".join(tail_chapters)
        return result[:max_chars]

    middle_chapters = chapters[head_count:n - tail_count] if tail_count > 0 else chapters[head_count:]
    if not middle_chapters:
        result = "\n".join(head_chapters + tail_chapters)
        return result[:max_chars]

    avg_chapter_chars = sum(len(c) for c in middle_chapters) / len(middle_chapters) if middle_chapters else 1
    max_middle_count = max(1, int(remaining_budget / avg_chapter_chars))

    step = max(1, len(middle_chapters) // max_middle_count)
    selected_middle = [middle_chapters[i] for i in range(0, len(middle_chapters), step)]

    current_chars = head_chars + tail_chars
    filtered_middle = []
    for ch in selected_middle:
        if current_chars + len(ch) <= max_chars:
            filtered_middle.append(ch)
            current_chars += len(ch)
        else:
            break

    all_selected = head_chapters + filtered_middle + tail_chapters
    result = "\n".join(all_selected)

    omitted = n - len(all_selected)
    if omitted > 0:
        result += f"\n\n---\n\n[已省略 {omitted} 章，仅保留 {len(all_selected)} 章代表性内容]"

    return result


def collect_novel_texts(
    novel_paths: list[Path], mode: str = "sample", max_chars: int = MAX_PROMPT_CHARS
) -> str:
    """收集所有小说文件的解析结果，并智能选取代表性章节

    Args:
        novel_paths: 小说文件路径列表（.txt 或 .epub）
        mode: 输出模式 - full / sample / preview
        max_chars: Prompt 中小说部分的最大字符数
    """
    results = []
    for path in novel_paths:
        if path.suffix.lower() == '.epub':
            chapters = parse_epub(path)
            for title, content in chapters:
                results.append(f"## {title}\n\n{content}")
        else:
            result = parse_novel(path, mode=mode)
            results.append(result)

    full_text = "\n\n---\n\n".join(results)
    return select_representative_chapters(full_text, max_chars)


def collect_comment_texts(comment_paths: list[Path], platform: str) -> str:
    """收集所有评论文件的解析结果

    Args:
        comment_paths: 评论文件路径列表
        platform: 评论平台 - 起点 / 晋江 / 番茄 / json
    """
    results = []
    for path in comment_paths:
        text = read_file_with_fallback(path)
        if platform == '起点':
            comments = parse_qidian_comments(text)
        elif platform == '晋江':
            comments = parse_jinjiang_comments(text)
        elif platform == '番茄':
            comments = parse_fanqie_comments(text)
        else:
            comments = parse_json_comments(text)

        # 格式化评论，标记作者回复
        for c in comments:
            prefix = "[作者回复] " if c.get('is_author') else ""
            user = c.get('user', '未知')
            content = c.get('content', '')
            results.append(f"{prefix}{user}：{content}")
    return "\n".join(results)


def collect_social_texts(social_paths: list[Path]) -> str:
    """收集所有社交媒体文件的解析结果

    .html/.htm 文件按微信公众号文章解析，其余按微博内容解析。
    """
    results = []
    for path in social_paths:
        text = read_file_with_fallback(path)
        if path.suffix.lower() in ('.html', '.htm') or is_html_content(text):
            article = parse_wechat_html(text)
            results.append(
                f"## {article['title']}\n作者：{article['author']}\n\n{article['content']}"
            )
        else:
            weibos = parse_weibo_json(text)
            if not weibos:
                weibos = parse_weibo_text(text)
            for w in weibos:
                nw = normalize_weibo(w)
                time_str = f"（{nw['time']}）" if nw['time'] else ''
                results.append(f"{time_str}{nw['content']}")
    return "\n".join(results)


# ---------------------------------------------------------------------------
# 分析 Prompt 构建
# ---------------------------------------------------------------------------

def build_writing_analysis_prompt(name: str, novel_text: str, comment_text: str) -> str:
    """构建写作风格分析 Prompt

    读取 prompts/writing_analyzer.md 模板，填充作者名和原材料。
    """
    prompts_dir = Path(__file__).parent.parent / "prompts"
    analyzer_prompt = (prompts_dir / "writing_analyzer.md").read_text(encoding="utf-8")
    analyzer_prompt = analyzer_prompt.replace("{name}", name)

    return f"""{analyzer_prompt}

---

## 原材料

### 小说正文

{novel_text}

### 评论数据

{comment_text}
"""


def build_persona_analysis_prompt(
    name: str, meta: dict, comment_text: str, social_text: str
) -> str:
    """构建作者人格分析 Prompt

    读取 prompts/author_persona_analyzer.md 模板，填充作者名、元数据和原材料。
    """
    prompts_dir = Path(__file__).parent.parent / "prompts"
    analyzer_prompt = (prompts_dir / "author_persona_analyzer.md").read_text(
        encoding="utf-8"
    )
    analyzer_prompt = analyzer_prompt.replace("{name}", name)

    tags_info = ""
    for key in ["writing_style_tags", "update_habit_tags", "personality_tags", "genre_tags"]:
        if key in meta:
            tags_info += f"- {key}: {meta[key]}\n"

    return f"""{analyzer_prompt}

---

## 用户手动填写的基础信息

{tags_info}

---

## 原材料

### 评论数据

{comment_text}

### 社交媒体内容

{social_text}
"""


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="网文作者蒸馏编排器")
    parser.add_argument("--slug", help="作者 slug（不提供则从笔名自动生成）")
    parser.add_argument("--name", required=True, help="作者笔名")
    parser.add_argument("--novels", nargs="*", default=[], help="小说文件路径列表")
    parser.add_argument("--comments", nargs="*", default=[], help="评论文件路径列表")
    parser.add_argument(
        "--platform",
        default="起点",
        choices=['起点', '晋江', '番茄', 'json'],
        help="评论平台",
    )
    parser.add_argument("--social", nargs="*", default=[], help="社交媒体文件路径列表")
    parser.add_argument(
        "--mode",
        default="sample",
        choices=['full', 'sample', 'preview'],
        help="小说输出模式",
    )
    parser.add_argument("--base-dir", default="./authors", help="作者 Skill 根目录")
    parser.add_argument(
        "--max-chars",
        type=int,
        default=MAX_PROMPT_CHARS,
        help=f"Prompt 中小说部分的最大字符数（默认 {MAX_PROMPT_CHARS}）",
    )

    # 可选元数据
    parser.add_argument("--platform-level", help="平台等级（如 LV5）")
    parser.add_argument("--masterpiece", help="代表作")
    parser.add_argument("--gender", help="性别")

    args = parser.parse_args()

    # 1. 生成 slug
    slug = args.slug or slugify(args.name)
    try:
        validate_slug(slug)
    except ValueError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)

    # 2. 构建元数据
    meta: dict = {"name": args.name}
    profile: dict = {}
    if args.platform_level:
        profile["platform"] = args.platform
        profile["level"] = args.platform_level
    if args.masterpiece:
        profile["masterpiece"] = args.masterpiece
    if args.gender:
        meta["gender"] = args.gender
    if profile:
        meta["profile"] = profile

    # 3. 解析原材料
    novel_paths = [Path(p) for p in args.novels]
    comment_paths = [Path(p) for p in args.comments]
    social_paths = [Path(p) for p in args.social]

    novel_text = collect_novel_texts(novel_paths, args.mode, args.max_chars) if novel_paths else ""
    comment_text = (
        collect_comment_texts(comment_paths, args.platform) if comment_paths else ""
    )
    social_text = collect_social_texts(social_paths) if social_paths else ""

    if not novel_text and not comment_text and not social_text:
        print("错误：至少需要提供一种原材料（小说/评论/社交媒体）", file=sys.stderr)
        sys.exit(1)

    # 4. 生成分析 Prompt
    writing_prompt = build_writing_analysis_prompt(args.name, novel_text, comment_text)
    persona_prompt = build_persona_analysis_prompt(
        args.name, meta, comment_text, social_text
    )

    # 5. 输出 Prompt 供 LLM 处理
    base_dir = Path(args.base_dir)
    prompt_dir = base_dir / slug / "knowledge"
    prompt_dir.mkdir(parents=True, exist_ok=True)

    (prompt_dir / "writing_analysis_prompt.md").write_text(
        writing_prompt, encoding="utf-8"
    )
    (prompt_dir / "persona_analysis_prompt.md").write_text(
        persona_prompt, encoding="utf-8"
    )

    # 6. 输出解析后的原材料
    if novel_text:
        (prompt_dir / "novel_parsed.txt").write_text(novel_text, encoding="utf-8")
    if comment_text:
        (prompt_dir / "comment_parsed.txt").write_text(comment_text, encoding="utf-8")
    if social_text:
        (prompt_dir / "social_parsed.txt").write_text(social_text, encoding="utf-8")

    print("蒸馏准备完成！")
    print(f"  作者：{args.name}（{slug}）")
    print(f"  小说文件：{len(novel_paths)} 个")
    print(f"  评论文件：{len(comment_paths)} 个")
    print(f"  社交媒体：{len(social_paths)} 个")
    print(f"  输出模式：{args.mode}")
    print()
    print(f"分析 Prompt 已生成到：{prompt_dir}")
    print()
    print("下一步：将 writing_analysis_prompt.md 和 persona_analysis_prompt.md")
    print("分别发送给 LLM，获取分析结果后使用 skill_writer.py 生成 Skill 文件。")
    print()
    print("或者使用 --auto 模式自动调用 LLM（需要配置 API key）。")


if __name__ == "__main__":
    main()
