#!/usr/bin/env python3
"""
迭代蒸馏编排器

支持两种操作：
- init: 首轮初始化（解析小说，采样前 5~10 章，生成初始 skill）
- evolve: 迭代进化轮次（采样新章节 + 读取当前 skill + 调用重整 prompt + 写入新 skill）

用法：
    python iterative_distill.py --action init --slug feitianyu --novel novel.txt --base-dir ./authors
    python iterative_distill.py --action evolve --slug feitianyu --novel novel.txt --strategy stratified --base-dir ./authors
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from chapter_sampler import (
    parse_novel_chapters,
    initial_sample,
    stratified_sample,
    uncertainty_sample,
    get_chapter_content,
)
from skill_writer import (
    create_skill,
    update_skill,
    validate_slug,
    slugify,
    render_skill_md,
    render_sub_skill_md,
    build_identity_string,
    atomic_write,
)
from novel_parser import parse_novel
from config import ENCODING_FALLBACK_ORDER


def read_file_with_fallback(path: Path) -> str:
    for encoding in ENCODING_FALLBACK_ORDER:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"无法以支持的编码读取文件：{path}")


def _load_merger_prompt() -> str:
    prompts_dir = Path(__file__).parent.parent / "prompts"
    return (prompts_dir / "merger.md").read_text(encoding="utf-8")


def _load_writing_analysis_prompt() -> str:
    prompts_dir = Path(__file__).parent.parent / "prompts"
    return (prompts_dir / "writing_analyzer.md").read_text(encoding="utf-8")


def _load_persona_analysis_prompt() -> str:
    prompts_dir = Path(__file__).parent.parent / "prompts"
    return (prompts_dir / "author_persona_analyzer.md").read_text(encoding="utf-8")


def _get_sampled_chapters(skill_dir: Path) -> list[int]:
    meta_path = skill_dir / "meta.json"
    if not meta_path.exists():
        return []
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        evolution = meta.get("evolution", {})
        return evolution.get("chapters_sampled", [])
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []


def _update_evolution_meta(
    skill_dir: Path,
    round_num: int,
    sampled_indices: list[int],
    strategy: str,
    version_before: Optional[str],
    version_after: str,
    updated_dimensions: list[str],
) -> None:
    meta_path = skill_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    if "evolution" not in meta:
        meta["evolution"] = {
            "total_rounds": 0,
            "chapters_sampled": [],
            "rounds": [],
            "convergence": {
                "is_converged": False,
                "last_validation_scores": None,
                "consecutive_small_gains": 0,
            },
        }

    evo = meta["evolution"]
    evo["total_rounds"] = round_num
    evo["chapters_sampled"] = sorted(
        set(evo.get("chapters_sampled", []) + sampled_indices)
    )

    round_record = {
        "round": round_num,
        "chapters": sampled_indices,
        "sampling_strategy": strategy,
        "version_before": version_before,
        "version_after": version_after,
        "updated_dimensions": updated_dimensions,
        "validation_score": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    evo["rounds"].append(round_record)

    meta["evolution"] = evo
    atomic_write(meta_path, json.dumps(meta, ensure_ascii=False, indent=2))


def _extract_updated_dimensions(old_writing: str, new_writing: str) -> list[str]:
    dimensions = [
        "叙事风格", "情节构建", "人物塑造", "世界观设定",
        "对话风格", "描写风格", "更新习惯",
    ]
    updated = []
    for dim in dimensions:
        old_section = _extract_section(old_writing, dim)
        new_section = _extract_section(new_writing, dim)
        if old_section != new_section:
            updated.append(dim)
    return updated if updated else ["未检测到显著变化"]


def _extract_section(text: str, heading: str) -> str:
    pattern = re.compile(
        rf'^##\s+{re.escape(heading)}\s*$(.*?)(?=^##\s|\Z)',
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def init_round(
    novel_path: Path,
    slug: str,
    base_dir: Path,
    count: int = 5,
    meta: Optional[dict] = None,
) -> Path:
    """
    首轮初始化：解析小说，采样前 N 章，生成初始 skill 的分析 Prompt。

    注意：此工具只准备数据和 Prompt，实际的 Skill 生成需要 LLM 处理。

    Args:
        novel_path: 小说文件路径
        slug: 作者 slug
        base_dir: 作者 Skill 根目录
        count: 首轮采样章数
        meta: 基础元数据

    Returns:
        Skill 目录路径
    """
    slug = validate_slug(slug)
    skill_dir = base_dir / slug

    if skill_dir.exists() and any(skill_dir.iterdir()):
        print(f"错误：作者 Skill 目录已存在且非空: {skill_dir}", file=sys.stderr)
        sys.exit(1)

    chapters = parse_novel_chapters(novel_path)
    if not chapters:
        print("错误：未识别到章节结构", file=sys.stderr)
        sys.exit(1)

    sampled = initial_sample(chapters, count)
    sampled_content = get_chapter_content(chapters, sampled)

    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "versions").mkdir(exist_ok=True)
    (skill_dir / "knowledge" / "novels").mkdir(parents=True, exist_ok=True)
    (skill_dir / "knowledge" / "comments").mkdir(parents=True, exist_ok=True)
    (skill_dir / "knowledge" / "social").mkdir(parents=True, exist_ok=True)

    knowledge_dir = skill_dir / "knowledge"
    (knowledge_dir / "init_sampled_chapters.md").write_text(
        sampled_content, encoding="utf-8"
    )

    writing_prompt = _load_writing_analysis_prompt()
    name = meta.get("name", slug) if meta else slug
    writing_prompt = writing_prompt.replace("{name}", name)

    init_prompt = f"""{writing_prompt}

---

## 原材料

### 小说正文（首轮采样：前 {len(sampled)} 章）

{sampled_content}

### 评论数据

（首轮无评论数据）
"""

    (knowledge_dir / "init_analysis_prompt.md").write_text(
        init_prompt, encoding="utf-8"
    )

    sampled_titles = [chapters[i][0] for i in sampled]
    print(f"首轮初始化准备完成！")
    print(f"  作者 slug：{slug}")
    print(f"  采样章数：{len(sampled)}")
    print(f"  采样章节：{', '.join(sampled_titles)}")
    print(f"  采样索引：{', '.join(str(i) for i in sampled)}")
    print(f"  总字符数：{len(sampled_content)}")
    print()
    print(f"分析 Prompt 已生成到：{knowledge_dir / 'init_analysis_prompt.md'}")
    print()
    print("下一步：")
    print("1. 将 init_analysis_prompt.md 发送给 LLM 获取 Writing 分析结果")
    print("2. 参考 prompts/writing_builder.md 生成 writing.md")
    print("3. 参考 prompts/author_persona_builder.md 生成 author_persona.md")
    print("4. 使用 skill_writer.py --action create 写入 Skill 文件")
    print()
    print("或者直接使用 /create-author 命令交互式完成。")

    return skill_dir


def evolve_round(
    novel_path: Path,
    slug: str,
    base_dir: Path,
    strategy: str = "stratified",
    count: int = 5,
) -> None:
    """
    迭代进化轮次：采样新章节 + 读取当前 skill + 生成重整 Prompt。

    注意：此工具只准备数据和 Prompt，实际的 Skill 重整需要 LLM 处理。

    Args:
        novel_path: 小说文件路径
        slug: 作者 slug
        base_dir: 作者 Skill 根目录
        strategy: 采样策略 (stratified / uncertainty)
        count: 采样章数
    """
    slug = validate_slug(slug)
    skill_dir = base_dir / slug

    if not skill_dir.exists():
        print(f"错误：找不到 Skill 目录 {skill_dir}", file=sys.stderr)
        sys.exit(1)

    meta_path = skill_dir / "meta.json"
    if not meta_path.exists():
        print(f"错误：找不到 meta.json {meta_path}", file=sys.stderr)
        sys.exit(1)

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    current_version = meta.get("version", "v1")

    chapters = parse_novel_chapters(novel_path)
    if not chapters:
        print("错误：未识别到章节结构", file=sys.stderr)
        sys.exit(1)

    already_sampled = set(_get_sampled_chapters(skill_dir))

    if strategy == "uncertainty":
        writing_path = skill_dir / "writing.md"
        persona_path = skill_dir / "author_persona.md"
        skill_text = ""
        if writing_path.exists():
            skill_text += writing_path.read_text(encoding="utf-8")
        if persona_path.exists():
            skill_text += "\n\n" + persona_path.read_text(encoding="utf-8")
        sampled = uncertainty_sample(chapters, skill_text, count, already_sampled)
    else:
        sampled = stratified_sample(chapters, count, already_sampled)

    if not sampled:
        print("所有章节已采样完毕，无法继续进化", file=sys.stderr)
        sys.exit(0)

    sampled_content = get_chapter_content(chapters, sampled)

    writing_content = ""
    writing_path = skill_dir / "writing.md"
    if writing_path.exists():
        writing_content = writing_path.read_text(encoding="utf-8")

    persona_content = ""
    persona_path = skill_dir / "author_persona.md"
    if persona_path.exists():
        persona_content = persona_path.read_text(encoding="utf-8")

    merger_prompt = _load_merger_prompt()

    evolve_prompt = f"""{merger_prompt}

---

## 现有 writing.md

{writing_content}

---

## 现有 author_persona.md

{persona_content}

---

## 新采样的章节（{len(sampled)} 章）

{sampled_content}
"""

    knowledge_dir = skill_dir / "knowledge"
    round_num = meta.get("evolution", {}).get("total_rounds", 0) + 1

    evolve_prompt_path = knowledge_dir / f"evolve_round{round_num}_prompt.md"
    evolve_prompt_path.write_text(evolve_prompt, encoding="utf-8")

    sampled_chapters_path = knowledge_dir / f"evolve_round{round_num}_sampled.md"
    sampled_chapters_path.write_text(sampled_content, encoding="utf-8")

    sampled_titles = [chapters[i][0] for i in sampled]
    print(f"进化轮次 Round {round_num} 准备完成！")
    print(f"  当前版本：{current_version}")
    print(f"  采样策略：{strategy}")
    print(f"  采样章数：{len(sampled)}")
    print(f"  采样章节：{', '.join(sampled_titles)}")
    print(f"  采样索引：{', '.join(str(i) for i in sampled)}")
    print(f"  总字符数：{len(sampled_content)}")
    print()
    print(f"重整 Prompt 已生成到：{evolve_prompt_path}")
    print()
    print("下一步：")
    print(f"1. 将 {evolve_prompt_path.name} 发送给 LLM 获取重整后的 writing.md 和 author_persona.md")
    print("2. 存档当前版本：")
    print(f"   python version_manager.py --action backup --slug {slug} --base-dir {base_dir}")
    print("3. 将 LLM 输出的重写后 writing.md 和 author_persona.md 写入对应文件")
    print("4. 重新生成 SKILL.md（合并最新的 writing.md + author_persona.md）")
    print("5. 更新 meta.json 的 version 和 evolution 字段")
    print()
    print("或者直接使用 /evolve-author 命令交互式完成。")


def main():
    parser = argparse.ArgumentParser(description="迭代蒸馏编排器")
    parser.add_argument(
        "--action",
        required=True,
        choices=["init", "evolve"],
        help="操作类型：init=首轮初始化，evolve=迭代进化",
    )
    parser.add_argument("--slug", required=True, help="作者 slug")
    parser.add_argument("--novel", required=True, help="小说文件路径")
    parser.add_argument(
        "--strategy",
        default="stratified",
        choices=["stratified", "uncertainty"],
        help="进化采样策略（默认：stratified）",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=5,
        help="采样章数（默认：5）",
    )
    parser.add_argument(
        "--base-dir",
        default="./authors",
        help="作者 Skill 根目录（默认：./authors）",
    )
    parser.add_argument("--name", help="作者笔名（init 时使用）")

    args = parser.parse_args()

    novel_path = Path(args.novel)
    if not novel_path.exists():
        print(f"错误：文件不存在 {novel_path}", file=sys.stderr)
        sys.exit(1)

    base_dir = Path(args.base_dir).expanduser()

    if args.action == "init":
        meta = {}
        if args.name:
            meta["name"] = args.name
        init_round(novel_path, args.slug, base_dir, args.count, meta)

    elif args.action == "evolve":
        evolve_round(novel_path, args.slug, base_dir, args.strategy, args.count)


if __name__ == "__main__":
    main()
