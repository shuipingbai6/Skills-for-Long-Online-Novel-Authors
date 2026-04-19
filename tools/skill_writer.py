#!/usr/bin/env python3
"""
Author Skill 文件写入器

负责将生成的 writing.md、author_persona.md 写入到正确的目录结构，
并生成 meta.json 和完整的 SKILL.md。

用法：
    python skill_writer.py --action create --slug feitianyu --meta meta.json \
        --writing writing_content.md --persona persona_content.md \
        --base-dir ./authors

    python skill_writer.py --action update --slug feitianyu \
        --writing-patch writing_patch.md --persona-patch persona_patch.md \
        --base-dir ./authors

    python skill_writer.py --action update --slug feitianyu \
        --correction-wrong "用被动语态" --correction-correct "用主动语态" \
        --correction-scene "对话描写"

    python skill_writer.py --action list --base-dir ./authors
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import argparse
import sys
import warnings
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

SKILL_FILES = (
    "SKILL.md",
    "writing.md",
    "author_persona.md",
    "writing_skill.md",
    "persona_skill.md",
)

SLUG_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def validate_slug(slug: str) -> str:
    """校验 slug 安全性，防止路径遍历"""
    if not SLUG_RE.match(slug):
        raise ValueError(f"无效的 slug: {slug!r}，仅允许小写字母、数字和连字符")
    return slug


def slugify(name: str) -> str:
    """
    将笔名转为 slug。
    优先尝试 pypinyin（如已安装），否则 fallback 到简单处理。
    """
    try:
        from pypinyin import lazy_pinyin
        parts = lazy_pinyin(name)
        slug = "-".join(parts)
    except ImportError:
        warnings.warn(
            "pypinyin 未安装，slugify 将使用简单 ASCII fallback，"
            "中文笔名可能生成不理想的 slug。建议安装：pip install pypinyin",
            stacklevel=2,
        )
        import unicodedata
        result = []
        for char in name:
            normalized = unicodedata.normalize('NFKD', char)
            ascii_part = ''.join(c for c in normalized if c.isascii() and c.isalnum())
            if ascii_part:
                result.append(ascii_part.lower())
            elif char == ' ':
                result.append('-')
        slug = "-".join(result) if result else ""

    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug:
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:4]
        slug = f"author-{digest}"
    return slug


def build_identity_string(meta: dict) -> str:
    """从 meta 构建身份描述字符串"""
    profile = meta.get("profile", {})
    parts = []

    platform = profile.get("platform", "")
    level = profile.get("level", "")
    masterpiece = profile.get("masterpiece", "")

    if platform:
        parts.append(platform)
    if level:
        parts.append(level)
    if masterpiece:
        parts.append(f"代表作《{masterpiece}》")

    identity = " ".join(parts) if parts else "作者"

    return identity


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write(path: Path, content: str, encoding: str = "utf-8") -> None:
    """原子写入：先写临时文件再重命名，防止写入中断导致文件损坏"""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp_path.write_text(content, encoding=encoding)
        tmp_path.replace(path)
    except BaseException:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


# ---------------------------------------------------------------------------
# SKILL.md 生成（分段拼接，避免 Template 注入）
# ---------------------------------------------------------------------------

def render_skill_md(
    slug: str,
    name: str,
    identity: str,
    writing_content: str,
    persona_content: str,
) -> str:
    """
    生成 SKILL.md 内容。
    使用分段拼接而非 Template.substitute()，避免用户内容中的
    ${xxx} 被误替换导致崩溃或内容篡改。
    """
    front_matter = (
        f"---\n"
        f"name: author_{slug}\n"
        f"description: {name}，{identity}\n"
        f"user-invocable: true\n"
        f"---\n"
    )

    header = (
        f"\n# {name}\n"
        f"\n{identity}\n"
        f"\n---\n"
        f"\n## PART A：写作能力\n"
    )

    middle = (
        f"\n{writing_content}\n"
        f"\n---\n"
        f"\n## PART B：作者人格\n"
    )

    footer = (
        f"\n{persona_content}\n"
        f"\n---\n"
        f"\n## 运行规则\n"
        f"\n接收到任何任务或问题时：\n"
        f"\n"
        f"1. **先由 PART B 判断**：你会用什么态度接这个任务？\n"
        f"2. **再由 PART A 执行**：用你的写作能力和风格完成任务\n"
        f"3. **输出时保持 PART B 的表达风格**：你说话的方式、用词习惯、句式\n"
        f"\n"
        f"**PART B 的 Layer 0 规则永远优先，任何情况下不得违背。**\n"
    )

    return front_matter + header + middle + footer


# ---------------------------------------------------------------------------
# 子 Skill 文件生成（提取重复代码）
# ---------------------------------------------------------------------------

def render_sub_skill_md(slug: str, name: str, kind: str, content: str) -> str:
    """
    生成 writing_skill.md 或 persona_skill.md 内容。

    :param slug: 作者 slug
    :param name: 作者笔名
    :param kind: "writing" 或 "persona"
    :param content: 对应的 markdown 正文
    """
    if kind == "writing":
        sub_name = f"author_{slug}_writing"
        desc = f"{name} 的写作能力（仅 Writing，无 Persona）"
    elif kind == "persona":
        sub_name = f"author_{slug}_persona"
        desc = f"{name} 的作者人格（仅 Persona，无写作能力）"
    else:
        raise ValueError(f"未知的 kind: {kind!r}，应为 'writing' 或 'persona'")

    return (
        f"---\n"
        f"name: {sub_name}\n"
        f"description: {desc}\n"
        f"user-invocable: true\n"
        f"---\n"
        f"\n{content}\n"
    )


# ---------------------------------------------------------------------------
# 核心操作
# ---------------------------------------------------------------------------

def create_skill(
    base_dir: Path,
    slug: str,
    meta: dict,
    writing_content: str,
    persona_content: str,
) -> Path:
    """创建新的作者 Skill 目录结构"""

    slug = validate_slug(slug)
    skill_dir = base_dir / slug

    if skill_dir.resolve().is_relative_to(base_dir.resolve()) is False:
        raise ValueError(f"slug 导致路径越界: {slug!r}")

    if skill_dir.exists() and any(skill_dir.iterdir()):
        raise FileExistsError(f"作者 Skill 目录已存在且非空: {skill_dir}")

    if not writing_content.strip():
        raise ValueError("writing_content 不能为空")
    if not persona_content.strip():
        raise ValueError("persona_content 不能为空")

    skill_dir.mkdir(parents=True, exist_ok=True)

    (skill_dir / "versions").mkdir(exist_ok=True)
    (skill_dir / "knowledge" / "novels").mkdir(parents=True, exist_ok=True)
    (skill_dir / "knowledge" / "comments").mkdir(parents=True, exist_ok=True)
    (skill_dir / "knowledge" / "social").mkdir(parents=True, exist_ok=True)

    atomic_write(skill_dir / "writing.md", writing_content)
    atomic_write(skill_dir / "author_persona.md", persona_content)

    name = meta.get("name", slug)
    identity = build_identity_string(meta)

    skill_md = render_skill_md(slug, name, identity, writing_content, persona_content)
    atomic_write(skill_dir / "SKILL.md", skill_md)

    writing_only = render_sub_skill_md(slug, name, "writing", writing_content)
    atomic_write(skill_dir / "writing_skill.md", writing_only)

    persona_only = render_sub_skill_md(slug, name, "persona", persona_content)
    atomic_write(skill_dir / "persona_skill.md", persona_only)

    now = utc_now_iso()
    meta["slug"] = slug
    meta.setdefault("created_at", now)
    meta["updated_at"] = now
    meta["version"] = "v1"
    meta.setdefault("corrections_count", 0)

    atomic_write(
        skill_dir / "meta.json",
        json.dumps(meta, ensure_ascii=False, indent=2),
    )

    return skill_dir


def update_skill(
    skill_dir: Path,
    base_dir: Path,
    writing_patch: Optional[str] = None,
    persona_patch: Optional[str] = None,
    correction: Optional[dict] = None,
) -> str:
    """更新现有 Skill，先存档当前版本，再写入更新"""

    # 路径校验：skill_dir 必须在 base_dir 下
    if not skill_dir.resolve().is_relative_to(base_dir.resolve()):
        raise ValueError(f"Skill 目录越界: {skill_dir} 不在 {base_dir} 下")

    meta_path = skill_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    current_version = meta.get("version", "v1")
    try:
        version_str = current_version.removeprefix("v").split("_")[0]
        version_num = int(version_str) + 1
    except ValueError:
        version_num = 2
    new_version = f"v{version_num}"

    # 版本号冲突检测
    new_version_dir = skill_dir / "versions" / new_version
    if new_version_dir.exists():
        raise FileExistsError(
            f"版本目录已存在: {new_version_dir}，可能存在并发写入冲突"
        )

    version_dir = skill_dir / "versions" / current_version
    version_dir.mkdir(parents=True, exist_ok=True)
    for fname in SKILL_FILES:
        src = skill_dir / fname
        if src.exists():
            shutil.copy2(src, version_dir / fname)

    if writing_patch:
        current_writing = (skill_dir / "writing.md").read_text(encoding="utf-8")
        new_writing = current_writing + "\n\n" + writing_patch
        atomic_write(skill_dir / "writing.md", new_writing)

    if persona_patch or correction:
        current_persona = (skill_dir / "author_persona.md").read_text(encoding="utf-8")
        new_persona = current_persona

        if persona_patch:
            new_persona = new_persona + "\n\n" + persona_patch

        if correction:
            wrong = correction.get("wrong")
            correct = correction.get("correct")
            if not wrong or not correct:
                raise ValueError("correction 必须包含 'wrong' 和 'correct' 字段")
            scene = correction.get("scene", "通用")
            correction_line = (
                f"\n- [{scene}] "
                f"不应该 {wrong}，应该 {correct}"
            )
            # 用正则匹配行首的 "## Correction 记录"
            match = re.search(r'^## Correction 记录\s*$', new_persona, re.MULTILINE)
            if match:
                insert_pos = match.end()
                rest = new_persona[insert_pos:]
                skip = "\n\n（暂无记录）"
                if rest.startswith(skip):
                    rest = rest[len(skip):]
                new_persona = new_persona[:insert_pos] + correction_line + rest
            else:
                new_persona = (
                    new_persona
                    + f"\n\n## Correction 记录\n{correction_line}\n"
                )
            meta["corrections_count"] = meta.get("corrections_count", 0) + 1

        atomic_write(skill_dir / "author_persona.md", new_persona)

    writing_content = (skill_dir / "writing.md").read_text(encoding="utf-8")
    persona_content = (skill_dir / "author_persona.md").read_text(encoding="utf-8")
    name = meta.get("name", skill_dir.name)
    identity = build_identity_string(meta)

    skill_md = render_skill_md(skill_dir.name, name, identity, writing_content, persona_content)
    atomic_write(skill_dir / "SKILL.md", skill_md)

    writing_only = render_sub_skill_md(skill_dir.name, name, "writing", writing_content)
    atomic_write(skill_dir / "writing_skill.md", writing_only)

    persona_only = render_sub_skill_md(skill_dir.name, name, "persona", persona_content)
    atomic_write(skill_dir / "persona_skill.md", persona_only)

    meta["version"] = new_version
    meta["updated_at"] = utc_now_iso()
    atomic_write(meta_path, json.dumps(meta, ensure_ascii=False, indent=2))

    return new_version


def list_authors(base_dir: Path) -> list[dict]:
    """列出所有已创建的作者 Skill"""
    authors = []

    if not base_dir.exists():
        return authors

    for skill_dir in sorted(base_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        meta_path = skill_dir / "meta.json"
        if not meta_path.exists():
            continue

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"警告: 跳过无效的 meta.json: {meta_path} ({e})", file=sys.stderr)
            continue

        authors.append({
            "slug": meta.get("slug", skill_dir.name),
            "name": meta.get("name", skill_dir.name),
            "identity": build_identity_string(meta),
            "version": meta.get("version", "v1"),
            "updated_at": meta.get("updated_at", ""),
            "corrections_count": meta.get("corrections_count", 0),
        })

    return authors


def main() -> None:
    parser = argparse.ArgumentParser(description="Author Skill 文件写入器")
    parser.add_argument("--action", required=True, choices=["create", "update", "list"])
    parser.add_argument("--slug", help="作者 slug（用于目录名）")
    parser.add_argument("--name", help="作者笔名")
    parser.add_argument("--meta", help="meta.json 文件路径")
    parser.add_argument("--writing", help="writing.md 内容文件路径")
    parser.add_argument("--persona", help="author_persona.md 内容文件路径")
    parser.add_argument("--writing-patch", help="writing.md 增量更新内容文件路径")
    parser.add_argument("--persona-patch", help="author_persona.md 增量更新内容文件路径")
    parser.add_argument(
        "--correction-wrong",
        help="correction：不应该出现的行为",
    )
    parser.add_argument(
        "--correction-correct",
        help="correction：应该出现的行为",
    )
    parser.add_argument(
        "--correction-scene",
        default="通用",
        help="correction：场景标签（默认：通用）",
    )
    parser.add_argument(
        "--base-dir",
        default="./authors",
        help="作者 Skill 根目录（默认：./authors）",
    )

    args = parser.parse_args()
    base_dir = Path(args.base_dir).expanduser()

    if args.action == "list":
        authors = list_authors(base_dir)
        if not authors:
            print("暂无已创建的作者 Skill")
        else:
            print(f"已创建 {len(authors)} 个作者 Skill：\n")
            for a in authors:
                updated = a["updated_at"][:10] if a["updated_at"] else "未知"
                print(f"  [{a['slug']}]  {a['name']} — {a['identity']}")
                print(f"    版本: {a['version']}  纠正次数: {a['corrections_count']}  更新: {updated}")
                print()

    elif args.action == "create":
        if not args.slug and not args.name:
            print("错误：create 操作需要 --slug 或 --name", file=sys.stderr)
            sys.exit(1)

        meta: dict = {}
        if args.meta:
            try:
                meta = json.loads(Path(args.meta).read_text(encoding="utf-8"))
            except FileNotFoundError:
                print(f"错误: 文件不存在: {args.meta}", file=sys.stderr)
                sys.exit(1)
            except json.JSONDecodeError as e:
                print(f"错误: JSON 格式无效: {args.meta} ({e})", file=sys.stderr)
                sys.exit(1)
        if args.name:
            meta["name"] = args.name

        slug = args.slug or slugify(meta.get("name", "author"))

        writing_content = ""
        if args.writing:
            writing_content = Path(args.writing).read_text(encoding="utf-8")

        persona_content = ""
        if args.persona:
            persona_content = Path(args.persona).read_text(encoding="utf-8")

        try:
            skill_dir = create_skill(base_dir, slug, meta, writing_content, persona_content)
        except (ValueError, FileExistsError) as e:
            print(f"错误：{e}", file=sys.stderr)
            sys.exit(1)
        print(f"作者 Skill 已创建：{skill_dir}")
        print(f"   触发词：/{slug}")

    elif args.action == "update":
        if not args.slug:
            print("错误：update 操作需要 --slug", file=sys.stderr)
            sys.exit(1)

        # 校验 slug 安全性
        try:
            validate_slug(args.slug)
        except ValueError as e:
            print(f"错误：{e}", file=sys.stderr)
            sys.exit(1)

        skill_dir = base_dir / args.slug
        if not skill_dir.exists():
            print(f"错误：找不到 Skill 目录 {skill_dir}", file=sys.stderr)
            sys.exit(1)

        writing_patch = Path(args.writing_patch).read_text(encoding="utf-8") if args.writing_patch else None
        persona_patch = Path(args.persona_patch).read_text(encoding="utf-8") if args.persona_patch else None

        # 构建 correction 字典
        correction = None
        if args.correction_wrong or args.correction_correct:
            if not args.correction_wrong or not args.correction_correct:
                print(
                    "错误：--correction-wrong 和 --correction-correct 必须同时提供",
                    file=sys.stderr,
                )
                sys.exit(1)
            correction = {
                "wrong": args.correction_wrong,
                "correct": args.correction_correct,
                "scene": args.correction_scene,
            }

        try:
            new_version = update_skill(
                skill_dir, base_dir, writing_patch, persona_patch, correction,
            )
        except (ValueError, OSError, FileExistsError) as e:
            print(f"错误：更新失败 - {e}", file=sys.stderr)
            sys.exit(1)
        print(f"Skill 已更新到 {new_version}：{skill_dir}")


if __name__ == "__main__":
    main()
