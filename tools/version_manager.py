#!/usr/bin/env python3
"""
版本管理器

负责 Author Skill 文件的版本存档和回滚。

用法：
    python version_manager.py --action list --slug feitianyu --base-dir ./authors
    python version_manager.py --action rollback --slug feitianyu --version v2 --base-dir ./authors
    python version_manager.py --action backup --slug feitianyu --base-dir ./authors
    python version_manager.py --action cleanup --slug feitianyu --base-dir ./authors
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

MAX_VERSIONS = 10

# ── 同步点：与 skill_writer.py 的 SKILL_FILES 保持一致 ──
# skill_writer.py 还会生成 writing_skill.md 和 persona_skill.md，
# 版本管理也需覆盖这两个衍生文件。
SKILL_FILES = (
    "SKILL.md",
    "writing.md",
    "author_persona.md",
    "writing_skill.md",
    "persona_skill.md",
    "meta.json",  # #12: meta.json 也纳入备份
)

SLUG_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')


def validate_slug(slug: str) -> str:
    """校验 slug 安全性，防止路径遍历"""
    if not SLUG_RE.match(slug):
        raise ValueError(f"无效的 slug: {slug!r}，仅允许小写字母、数字和连字符")
    return slug


def _version_sort_key(d: Path) -> tuple:
    """版本目录排序键：提取版本号数字排序，避免 v10 排在 v2 前面"""
    m = re.match(r'^v(\d+)', d.name)
    if m:
        return (0, int(m.group(1)))
    return (1, d.name)


def list_versions(skill_dir: Path) -> list[dict]:
    """列出所有历史版本"""
    versions_dir = skill_dir / "versions"
    if not versions_dir.exists():
        return []

    versions = []
    for v_dir in sorted(versions_dir.iterdir(), key=_version_sort_key):
        if not v_dir.is_dir():
            continue

        if "_before_rollback" in v_dir.name:
            continue

        version_name = v_dir.name

        try:
            mtime = v_dir.stat().st_mtime
            archived_at = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        except OSError:
            archived_at = "未知"

        files = sorted(f.name for f in v_dir.iterdir() if f.is_file())

        versions.append({
            "version": version_name,
            "archived_at": archived_at,
            "files": files,
            "path": str(v_dir),
        })

    return versions


def backup(skill_dir: Path) -> str:
    """备份当前版本到 versions 目录"""
    meta_path = skill_dir / "meta.json"
    if not meta_path.exists():
        raise ValueError(f"找不到 meta.json: {meta_path}")

    # #4: json.loads 异常保护
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"meta.json 解析失败: {e}") from e

    current_version = meta.get("version", "v1")

    version_dir = skill_dir / "versions" / current_version

    # #8: 版本存档已存在时输出警告
    if version_dir.exists():
        print(f"警告：版本存档 {current_version} 已存在，将被覆盖", file=sys.stderr)

    version_dir.mkdir(parents=True, exist_ok=True)

    for fname in SKILL_FILES:
        src = skill_dir / fname
        if src.exists():
            try:
                shutil.copy2(src, version_dir / fname)
            except (OSError, shutil.Error) as e:
                raise OSError(f"备份文件 {fname} 失败: {e}") from e

    return current_version


def rollback(skill_dir: Path, target_version: str) -> bool:
    """回滚到指定版本（原子性：先移走当前文件，再恢复目标版本，失败则回退）"""
    version_dir = skill_dir / "versions" / target_version

    if not version_dir.exists():
        print(f"错误：版本 {target_version} 不存在", file=sys.stderr)
        return False

    meta_path = skill_dir / "meta.json"
    meta = None
    current_version = "v?"
    if meta_path.exists():
        # #4: json.loads 异常保护
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            print("警告：meta.json 解析失败，将跳过元数据更新", file=sys.stderr)
            meta = None
        else:
            current_version = meta.get("version", "v?")

            # #5: 微秒级后缀避免目录碰撞
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
            backup_dir = skill_dir / "versions" / f"{current_version}_before_rollback_{timestamp}"
            try:
                backup_dir.mkdir(parents=True, exist_ok=False)
            except FileExistsError:
                # 极端情况：微秒碰撞，加随机后缀
                import random
                backup_dir = skill_dir / "versions" / f"{current_version}_before_rollback_{timestamp}_{random.randint(0,9999)}"
                backup_dir.mkdir(parents=True, exist_ok=False)

            for fname in SKILL_FILES:
                src = skill_dir / fname
                if src.exists():
                    try:
                        shutil.copy2(src, backup_dir / fname)
                    except (OSError, shutil.Error) as e:
                        print(f"错误：备份文件 {fname} 失败: {e}", file=sys.stderr)
                        return False

    # ── #1: 原子性回滚 ──
    # 第一步：将当前文件移到临时位置
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        moved_files = []
        for fname in SKILL_FILES:
            src = skill_dir / fname
            if src.exists():
                try:
                    shutil.move(str(src), str(tmp_path / fname))
                    moved_files.append(fname)
                except (OSError, shutil.Error) as e:
                    # 移动失败，回退已移动的文件
                    for mf in moved_files:
                        tmp_src = tmp_path / mf
                        if tmp_src.exists():
                            shutil.move(str(tmp_src), str(skill_dir / mf))
                    print(f"错误：移动文件 {fname} 到临时目录失败: {e}", file=sys.stderr)
                    return False

        # 第二步：从目标版本恢复
        try:
            for fname in SKILL_FILES:
                version_src = version_dir / fname
                if version_src.exists():
                    shutil.copy2(version_src, skill_dir / fname)
        except (OSError, shutil.Error) as e:
            # 恢复失败，回退：将临时位置的文件移回
            for fname in moved_files:
                tmp_src = tmp_path / fname
                if tmp_src.exists():
                    try:
                        shutil.move(str(tmp_src), str(skill_dir / fname))
                    except (OSError, shutil.Error):
                        print(f"严重错误：回退文件 {fname} 失败，数据可能丢失", file=sys.stderr)
            print(f"错误：恢复文件失败: {e}", file=sys.stderr)
            return False

    restored_files = [fname for fname in SKILL_FILES if (skill_dir / fname).exists()]

    if meta is not None and meta_path.exists():
        meta["version"] = target_version
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        meta["rollback_from"] = current_version
        # #3: meta.json 原子更新
        tmp_meta = meta_path.with_suffix(".tmp")
        tmp_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_meta.replace(meta_path)

    print(f"已回滚到 {target_version}，恢复文件：{', '.join(restored_files)}")
    return True


def cleanup_old_versions(skill_dir: Path, max_versions: int = MAX_VERSIONS):
    """清理超出限制的旧版本（包括 _before_rollback 目录）"""
    versions_dir = skill_dir / "versions"
    if not versions_dir.exists():
        return

    # 普通版本目录
    version_dirs = sorted(
        [d for d in versions_dir.iterdir() if d.is_dir() and "_before_rollback" not in d.name],
        key=_version_sort_key,
    )

    to_delete = version_dirs[:-max_versions] if len(version_dirs) > max_versions else []

    for old_dir in to_delete:
        try:
            shutil.rmtree(old_dir)
            print(f"已清理旧版本：{old_dir.name}")
        except (OSError, shutil.Error) as e:
            print(f"警告：清理 {old_dir.name} 失败: {e}", file=sys.stderr)

    # #6: 清理超过限制的 _before_rollback 目录
    rollback_dirs = sorted(
        [d for d in versions_dir.iterdir() if d.is_dir() and "_before_rollback" in d.name],
        key=lambda d: d.name,
    )

    rollback_to_delete = rollback_dirs[:-max_versions] if len(rollback_dirs) > max_versions else []

    for old_dir in rollback_to_delete:
        try:
            shutil.rmtree(old_dir)
            print(f"已清理回滚备份：{old_dir.name}")
        except (OSError, shutil.Error) as e:
            print(f"警告：清理回滚备份 {old_dir.name} 失败: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Author Skill 版本管理器")
    parser.add_argument("--action", required=True, choices=["list", "rollback", "backup", "cleanup"])
    parser.add_argument("--slug", required=True, help="作者 slug")
    parser.add_argument("--version", help="目标版本号（rollback 时使用）")
    parser.add_argument(
        "--base-dir",
        default="./authors",
        help="作者 Skill 根目录",
    )

    args = parser.parse_args()

    # #11: 使用 validate_slug 返回值
    try:
        slug = validate_slug(args.slug)
    except ValueError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)

    base_dir = Path(args.base_dir).expanduser().resolve()

    # #7: base-dir 安全验证
    cwd = Path.cwd().resolve()
    home = Path.home().resolve()
    try:
        base_dir.relative_to(cwd)
    except ValueError:
        try:
            base_dir.relative_to(home)
        except ValueError:
            print(
                f"错误：base-dir 必须位于当前工作目录 ({cwd}) 或用户目录 ({home}) 下",
                file=sys.stderr,
            )
            sys.exit(1)

    skill_dir = base_dir / slug

    if not skill_dir.exists():
        print(f"错误：找不到 Skill 目录 {skill_dir}", file=sys.stderr)
        sys.exit(1)

    if args.action == "list":
        versions = list_versions(skill_dir)
        if not versions:
            print(f"{slug} 暂无历史版本")
        else:
            print(f"{slug} 的历史版本：\n")
            for v in versions:
                print(f"  {v['version']}  存档时间: {v['archived_at']}  文件: {', '.join(v['files'])}")

    elif args.action == "backup":
        try:
            version = backup(skill_dir)
            print(f"已备份当前版本 {version}")
        except (ValueError, OSError, shutil.Error) as e:
            print(f"错误：备份失败 - {e}", file=sys.stderr)
            sys.exit(1)

    elif args.action == "rollback":
        if not args.version:
            print("错误：rollback 操作需要 --version", file=sys.stderr)
            sys.exit(1)
        success = rollback(skill_dir, args.version)
        if not success:
            sys.exit(1)
        cleanup_old_versions(skill_dir)

    elif args.action == "cleanup":
        cleanup_old_versions(skill_dir)
        print("清理完成")


if __name__ == "__main__":
    main()
