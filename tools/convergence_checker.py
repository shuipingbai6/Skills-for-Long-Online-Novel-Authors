#!/usr/bin/env python3
"""
收敛验证工具

支持两种操作：
- validate: 执行一轮完整验证（采样3章 → 生成骨架大纲 → 输出验证 Prompt）
- check: 判定收敛（基于历史评分数据）

用法：
    python convergence_checker.py --action validate --slug feitianyu --novel novel.txt --base-dir ./authors
    python convergence_checker.py --action check --slug feitianyu --base-dir ./authors
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
    stratified_sample,
    get_chapter_content,
)
from skill_writer import validate_slug, atomic_write
from config import ENCODING_FALLBACK_ORDER


def read_file_with_fallback(path: Path) -> str:
    for encoding in ENCODING_FALLBACK_ORDER:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"无法以支持的编码读取文件：{path}")


def _load_skeleton_prompt() -> str:
    prompts_dir = Path(__file__).parent.parent / "prompts"
    return (prompts_dir / "skeleton_outline.md").read_text(encoding="utf-8")


def _load_style_validator_prompt() -> str:
    prompts_dir = Path(__file__).parent.parent / "prompts"
    return (prompts_dir / "style_validator.md").read_text(encoding="utf-8")


def _get_already_sampled(skill_dir: Path) -> set[int]:
    meta_path = skill_dir / "meta.json"
    if not meta_path.exists():
        return set()
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        evolution = meta.get("evolution", {})
        return set(evolution.get("chapters_sampled", []))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return set()


def generate_skeleton_outline_prompt(chapter_content: str) -> str:
    """
    生成骨架大纲提取 Prompt。

    将骨架大纲模板与章节内容组合，发送给 LLM 提取骨架大纲。

    Args:
        chapter_content: 章节原文内容

    Returns:
        完整的骨架大纲提取 Prompt
    """
    skeleton_prompt = _load_skeleton_prompt()
    return f"""{skeleton_prompt}

---

## 待提取的章节原文

{chapter_content}
"""


def validate_round(
    slug: str,
    novel_path: Path,
    base_dir: Path,
) -> None:
    """
    执行一轮完整验证流程。

    步骤：
    1. 分层采样 3 章（前/中/后各 1 章）
    2. 生成骨架大纲提取 Prompt
    3. 生成风格评分 Prompt（供对比 AI 使用）

    注意：实际的骨架大纲提取和风格评分需要 LLM 处理，
    此工具只准备数据和 Prompt。

    Args:
        slug: 作者 slug
        novel_path: 小说文件路径
        base_dir: 作者 Skill 根目录
    """
    slug = validate_slug(slug)
    skill_dir = base_dir / slug

    if not skill_dir.exists():
        print(f"错误：找不到 Skill 目录 {skill_dir}", file=sys.stderr)
        sys.exit(1)

    writing_path = skill_dir / "writing.md"
    persona_path = skill_dir / "author_persona.md"
    if not writing_path.exists() or not persona_path.exists():
        print(f"错误：Skill 文件不完整，需要 writing.md 和 author_persona.md", file=sys.stderr)
        sys.exit(1)

    chapters = parse_novel_chapters(novel_path)
    if not chapters:
        print("错误：未识别到章节结构", file=sys.stderr)
        sys.exit(1)

    already_sampled = _get_already_sampled(skill_dir)
    sampled = stratified_sample(chapters, count=3, exclude=already_sampled)

    if len(sampled) < 3:
        available = [i for i in range(len(chapters)) if i not in already_sampled]
        if len(available) < 3:
            sampled = stratified_sample(chapters, count=3, exclude=set())
        else:
            sampled = stratified_sample(chapters, count=3, exclude=already_sampled)

    sampled_content = get_chapter_content(chapters, sampled)

    skeleton_prompt = generate_skeleton_outline_prompt(sampled_content)

    writing_content = writing_path.read_text(encoding="utf-8")
    persona_content = persona_path.read_text(encoding="utf-8")
    skill_content = f"# Writing Skill\n\n{writing_content}\n\n---\n\n# Author Persona\n\n{persona_content}"

    validator_prompt_template = _load_style_validator_prompt()

    validation_prompt = f"""# 收敛验证任务

## 操作步骤

### Step 1: 提取骨架大纲

使用以下 Prompt 从原文中提取骨架大纲：

{skeleton_prompt}

### Step 2: Skill AI 按大纲写作

将提取出的骨架大纲发送给加载了以下 Skill 的 AI，让它根据大纲写一章内容。

**Skill 内容**：

{skill_content}

### Step 3: 对比 AI 多维评分

将 Skill AI 生成的文本与原文一起发送给另一个 AI（必须与 Skill AI 不同），
按以下评分标准进行多维评分：

{validator_prompt_template}

---

## 验证用的原文章节

{sampled_content}
"""

    meta_path = skill_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    round_num = meta.get("evolution", {}).get("total_rounds", 0)

    knowledge_dir = skill_dir / "knowledge"
    validation_prompt_path = knowledge_dir / f"validation_round{round_num}_prompt.md"
    validation_prompt_path.write_text(validation_prompt, encoding="utf-8")

    sampled_titles = [chapters[i][0] for i in sampled]
    print(f"收敛验证准备完成！")
    print(f"  验证轮次：Round {round_num}")
    print(f"  采样章数：{len(sampled)}")
    print(f"  采样章节：{', '.join(sampled_titles)}")
    print(f"  采样索引：{', '.join(str(i) for i in sampled)}")
    print()
    print(f"验证 Prompt 已生成到：{validation_prompt_path}")
    print()
    print("验证步骤：")
    print("1. 将验证 Prompt 中的骨架大纲部分发送给 LLM，提取骨架大纲")
    print("2. 将骨架大纲发送给加载了 Skill 的 AI（Skill AI），让它写一章")
    print("3. 将 Skill AI 的输出 + 原文发送给另一个 AI（对比 AI），进行多维评分")
    print("4. 记录评分结果，使用 --action check 判定收敛")
    print()
    print("⚠️ 注意：Skill AI 和对比 AI 必须是不同的模型或不同的会话！")


def parse_validation_result(result_text: str) -> dict:
    """
    解析多维评分结果。

    从对比 AI 的输出中提取 5 维评分和综合分。

    Args:
        result_text: 对比 AI 的评分输出文本

    Returns:
        包含各维度分数和综合分的字典
    """
    scores = {}

    dimension_patterns = [
        ("叙事声音", r'叙事声音[|｜]\s*(\d+(?:\.\d+)?)'),
        ("节奏韵律", r'节奏韵律[|｜]\s*(\d+(?:\.\d+)?)'),
        ("对话风格", r'对话风格[|｜]\s*(\d+(?:\.\d+)?)'),
        ("描写偏好", r'描写偏好[|｜]\s*(\d+(?:\.\d+)?)'),
        ("用词习惯", r'用词习惯[|｜]\s*(\d+(?:\.\d+)?)'),
    ]

    for dim_name, pattern in dimension_patterns:
        match = re.search(pattern, result_text)
        if match:
            scores[dim_name] = float(match.group(1))

    comprehensive_match = re.search(
        r'(?:综合分|综合|overall)[|｜\s]*(\d+(?:\.\d+)?)',
        result_text,
        re.IGNORECASE,
    )
    if comprehensive_match:
        scores["综合分"] = float(comprehensive_match.group(1))
    elif len(scores) >= 5:
        values = [scores[k] for k in dimension_patterns if k[0] in scores]
        scores["综合分"] = round(sum(values) / len(values), 1)

    inconsistencies = []
    incon_pattern = re.compile(r'不一致处\s*\d+(.*?)(?=不一致处\s*\d+|##\s*总体|##\s*下一|$)', re.DOTALL)
    for match in incon_pattern.finditer(result_text):
        inconsistencies.append(match.group(1).strip())

    return {
        "scores": scores,
        "inconsistencies": inconsistencies,
        "raw_text": result_text,
    }


def check_convergence(
    history_scores: list[float],
    threshold: float = 0.3,
) -> dict:
    """
    判定收敛。

    核心判据：连续 2 轮迭代，5 维综合评分的提升幅度均 < threshold。

    Args:
        history_scores: 历史综合评分列表（按轮次顺序）
        threshold: 收敛阈值（默认 0.3）

    Returns:
        收敛判定结果字典
    """
    if len(history_scores) < 3:
        return {
            "is_converged": False,
            "reason": f"评分历史不足（{len(history_scores)}轮），至少需要3轮才能判定",
            "consecutive_small_gains": 0,
            "last_gain": None,
        }

    gains = []
    for i in range(1, len(history_scores)):
        gains.append(history_scores[i] - history_scores[i - 1])

    consecutive_small = 0
    for gain in reversed(gains):
        if abs(gain) < threshold:
            consecutive_small += 1
        else:
            break

    is_converged = consecutive_small >= 2

    overfitting = False
    if len(gains) >= 2:
        recent_gains = gains[-3:] if len(gains) >= 3 else gains
        if any(g < 0 for g in recent_gains[-2:]):
            overfitting = True

    return {
        "is_converged": is_converged,
        "overfitting_warning": overfitting,
        "consecutive_small_gains": consecutive_small,
        "last_gain": gains[-1] if gains else None,
        "threshold": threshold,
        "reason": (
            f"连续 {consecutive_small} 轮提升 < {threshold}，已收敛"
            if is_converged
            else f"最近提升 {gains[-1]:.1f}，未收敛" if gains else "数据不足"
        ),
    }


def record_validation_score(
    skill_dir: Path,
    score: float,
    dimension_scores: dict,
    inconsistencies: list[str],
) -> None:
    """
    将验证评分记录到 meta.json 的 evolution 字段中。

    Args:
        skill_dir: Skill 目录路径
        score: 综合评分
        dimension_scores: 各维度评分
        inconsistencies: 不一致处列表
    """
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

    if evo["rounds"]:
        last_round = evo["rounds"][-1]
        last_round["validation_score"] = score
        last_round["validation_dimensions"] = dimension_scores
        last_round["validation_inconsistencies"] = inconsistencies[:3]

    history_scores = []
    for r in evo["rounds"]:
        if r.get("validation_score") is not None:
            history_scores.append(r["validation_score"])

    convergence = check_convergence(history_scores)
    evo["convergence"] = {
        "is_converged": convergence["is_converged"],
        "overfitting_warning": convergence.get("overfitting_warning", False),
        "last_validation_scores": dimension_scores,
        "consecutive_small_gains": convergence["consecutive_small_gains"],
        "history_scores": history_scores,
    }

    meta["evolution"] = evo
    atomic_write(meta_path, json.dumps(meta, ensure_ascii=False, indent=2))

    print(f"验证评分已记录：综合分 {score}")
    print(f"收敛判定：{'已收敛' if convergence['is_converged'] else '未收敛'}")
    print(f"  原因：{convergence['reason']}")
    if convergence.get("overfitting_warning"):
        print("  ⚠️ 过拟合警告：近期评分出现下降趋势，建议回滚到评分最高版本")


def main():
    parser = argparse.ArgumentParser(description="收敛验证工具")
    parser.add_argument(
        "--action",
        required=True,
        choices=["validate", "check", "record"],
        help="操作类型：validate=执行验证，check=判定收敛，record=记录评分",
    )
    parser.add_argument("--slug", required=True, help="作者 slug")
    parser.add_argument("--novel", help="小说文件路径（validate 时需要）")
    parser.add_argument(
        "--base-dir",
        default="./authors",
        help="作者 Skill 根目录（默认：./authors）",
    )
    parser.add_argument(
        "--score",
        type=float,
        help="综合评分（record 时需要）",
    )
    parser.add_argument(
        "--dimension-scores",
        help="各维度评分 JSON（record 时需要），如 '{\"叙事声音\":7,\"节奏韵律\":6}'",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.3,
        help="收敛阈值（默认：0.3）",
    )

    args = parser.parse_args()

    slug = validate_slug(args.slug)
    base_dir = Path(args.base_dir).expanduser()
    skill_dir = base_dir / slug

    if not skill_dir.exists():
        print(f"错误：找不到 Skill 目录 {skill_dir}", file=sys.stderr)
        sys.exit(1)

    if args.action == "validate":
        if not args.novel:
            print("错误：validate 操作需要 --novel 参数", file=sys.stderr)
            sys.exit(1)
        novel_path = Path(args.novel)
        if not novel_path.exists():
            print(f"错误：文件不存在 {novel_path}", file=sys.stderr)
            sys.exit(1)
        validate_round(slug, novel_path, base_dir)

    elif args.action == "check":
        meta_path = skill_dir / "meta.json"
        if not meta_path.exists():
            print("错误：找不到 meta.json", file=sys.stderr)
            sys.exit(1)

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        evo = meta.get("evolution", {})

        history_scores = []
        for r in evo.get("rounds", []):
            if r.get("validation_score") is not None:
                history_scores.append(r["validation_score"])

        if not history_scores:
            print("尚无验证评分记录，请先执行 validate 操作")
            sys.exit(0)

        convergence = check_convergence(history_scores, args.threshold)

        print(f"评分历史：{' → '.join(f'{s:.1f}' for s in history_scores)}")
        print(f"收敛判定：{'已收敛 ✅' if convergence['is_converged'] else '未收敛 ❌'}")
        print(f"  原因：{convergence['reason']}")
        print(f"  连续小幅提升轮数：{convergence['consecutive_small_gains']}")
        print(f"  阈值：{convergence['threshold']}")

        if convergence.get("overfitting_warning"):
            print("  ⚠️ 过拟合警告：近期评分出现下降趋势，建议回滚到评分最高版本")

    elif args.action == "record":
        if args.score is None:
            print("错误：record 操作需要 --score 参数", file=sys.stderr)
            sys.exit(1)

        dimension_scores = {}
        if args.dimension_scores:
            try:
                dimension_scores = json.loads(args.dimension_scores)
            except json.JSONDecodeError as e:
                print(f"错误：维度评分 JSON 格式无效: {e}", file=sys.stderr)
                sys.exit(1)

        record_validation_score(skill_dir, args.score, dimension_scores, [])


if __name__ == "__main__":
    main()
