#!/usr/bin/env python3
"""
epub 小说解析器

支持解析 epub 格式的小说文件。

用法：
    python epub_parser.py --file novel.epub --output /tmp/epub_out.txt
    python epub_parser.py --file novel.epub --output /tmp/epub_out.txt --mode full
    python epub_parser.py --file novel.epub --output /tmp/epub_out.txt --mode sample --preview-length 800
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

MAX_EPUB_SIZE = 100 * 1024 * 1024
MAX_UNCOMPRESSED_SIZE = 500 * 1024 * 1024
COMPRESSION_RATIO_LIMIT = 100
SEPARATOR_WIDTH = 60
DEFAULT_PREVIEW_LENGTH = 500

try:
    from ebooklib import epub, ITEM_DOCUMENT
except ImportError:
    _DEPS_AVAILABLE = False
else:
    _DEPS_AVAILABLE = True

try:
    from lxml import etree  # noqa: F401
    BS4_PARSER = 'lxml'
except ImportError:
    BS4_PARSER = 'html.parser'

try:
    from bs4 import BeautifulSoup
except ImportError:
    _DEPS_AVAILABLE = False


def _check_deps() -> None:
    """检查依赖库是否可用"""
    if not _DEPS_AVAILABLE:
        raise RuntimeError(
            "缺少依赖库，请安装：pip install ebooklib beautifulsoup4 lxml"
        )


def _extract_title(soup: BeautifulSoup) -> str:
    """按优先级从 title/h1/h2/h3 中提取章节标题"""
    for selector in ('title', 'h1', 'h2', 'h3'):
        tag = soup.find(selector)
        if tag and tag.text.strip():
            return tag.text.strip()
    return '未命名章节'


def _validate_mimetype(file_path: Path) -> None:
    """验证 epub 的 mimetype 文件内容为 application/epub+zip"""
    try:
        with zipfile.ZipFile(str(file_path), 'r') as zf:
            try:
                mimetype_content = zf.read('mimetype').decode('ascii').strip()
            except KeyError:
                raise ValueError("不是有效的 epub 文件（缺少 mimetype 文件）")
            if mimetype_content != 'application/epub+zip':
                raise ValueError(
                    f"不是有效的 epub 文件（mimetype 为 '{mimetype_content}'，"
                    f"期望 'application/epub+zip'）"
                )
    except zipfile.BadZipFile as e:
        raise ValueError(f"文件不是有效的 ZIP/epub 格式") from e


def _check_zip_bomb(file_path: Path) -> None:
    """检测 Zip Bomb：解压后总大小限制和压缩比检测"""
    try:
        with zipfile.ZipFile(str(file_path), 'r') as zf:
            total_uncompressed = 0
            for info in zf.infolist():
                total_uncompressed += info.file_size
                if info.compress_size > 0:
                    ratio = info.file_size / info.compress_size
                    if ratio > COMPRESSION_RATIO_LIMIT:
                        raise ValueError(
                            f"检测到异常压缩比（{ratio:.1f}），文件可能为 Zip Bomb"
                        )
            if total_uncompressed > MAX_UNCOMPRESSED_SIZE:
                raise ValueError(
                    f"解压后总大小超过限制"
                    f"（{total_uncompressed // 1024 // 1024}MB"
                    f"> {MAX_UNCOMPRESSED_SIZE // 1024 // 1024}MB），"
                    f"可能存在安全风险"
                )
    except zipfile.BadZipFile as e:
        raise ValueError(f"文件不是有效的 ZIP/epub 格式") from e


def _validate_output_path(output_path: Path) -> None:
    """校验输出路径在项目目录内，防止路径遍历"""
    try:
        project_root = Path(__file__).resolve().parent.parent
        resolved = output_path.resolve()
        resolved.relative_to(project_root)
    except ValueError:
        raise ValueError(
            f"输出路径必须在项目目录内：{project_root}"
        )


def extract_metadata(file_path: Path) -> dict[str, str]:
    """
    提取 epub 元数据（书名、作者、语言等）

    Returns:
        包含 title / creator / language / publisher / description 等键的字典
    """
    _check_deps()
    book = epub.read_epub(str(file_path))

    metadata: dict[str, str] = {}
    for key, attr in [
        ('title', 'title'),
        ('creator', 'author'),
        ('language', 'language'),
        ('publisher', 'publisher'),
        ('description', 'description'),
    ]:
        value = book.get_metadata('DC', key)
        if value:
            # ebooklib 返回 list of (value, attrs) 元组
            metadata[attr] = value[0][0] if value[0] else ''
        else:
            metadata[attr] = ''

    return metadata


def parse_epub(file_path: Path) -> list[tuple[str, str]]:
    """
    解析 epub 文件，返回章节列表

    Returns:
        List of (章节标题, 章节内容)
    """
    _check_deps()
    book = epub.read_epub(str(file_path))

    # 按 spine 顺序获取文档项，保证阅读顺序
    spine_ids = [item_id for item_id, _linear in book.spine]
    id_to_item = {
        item.id: item
        for item in book.get_items()
        if item.get_type() == ITEM_DOCUMENT
    }

    chapters: list[tuple[str, str]] = []

    for item_id in spine_ids:
        item = id_to_item.get(item_id)
        if item is None:
            continue

        try:
            content_bytes = item.get_content()
        except (AttributeError, KeyError) as e:
            chapters.append((f'章节读取失败（{item_id}）', f'错误：{e}'))
            continue

        try:
            soup = BeautifulSoup(content_bytes, BS4_PARSER)
        except Exception as e:
            # 解析失败时尝试原始文本
            try:
                raw = content_bytes.decode('utf-8', errors='replace')
            except (UnicodeDecodeError, AttributeError):
                raw = str(content_bytes)
            chapters.append(('未命名章节', raw))
            continue

        title = _extract_title(soup)

        for script in soup(["script", "style"]):
            script.decompose()

        content = soup.get_text(separator='\n')
        content = '\n'.join(
            stripped for line in content.split('\n') if (stripped := line.strip())
        )

        # 空章节保留，标记为（空章节）
        if not content:
            content = '（空章节）'

        chapters.append((title, content))

    return chapters


def format_output(
    chapters: list[tuple[str, str]],
    file_name: str,
    mode: str = 'preview',
    preview_length: int = DEFAULT_PREVIEW_LENGTH,
) -> str:
    """
    格式化输出内容

    Args:
        chapters: 章节列表
        file_name: 文件名
        mode: 输出模式 - full（全部内容）/ sample（每章前 N 字）/ preview（预览摘要）
        preview_length: 预览/采样模式下每章显示的字数
    """
    total_words = sum(len(content) for _, content in chapters)

    output_lines: list[str] = []
    output_lines.append(f"epub 解析结果：{file_name}")
    output_lines.append(f"识别章节：{len(chapters)} 章")
    output_lines.append(f"总字数：{total_words}")
    output_lines.append("")
    output_lines.append("=" * SEPARATOR_WIDTH)
    output_lines.append("")

    for i, (title, content) in enumerate(chapters):
        word_count = len(content)

        output_lines.append(f"## 第{i + 1}章 {title}")
        output_lines.append(f"字数：{word_count}")
        output_lines.append("")

        if mode == 'full':
            output_lines.append(content)
        elif mode == 'sample':
            sample_len = min(preview_length, len(content))
            output_lines.append(content[:sample_len])
            if len(content) > sample_len:
                output_lines.append("...")
        else:  # preview
            output_lines.append("内容预览：")
            preview_len = min(preview_length, len(content))
            output_lines.append(content[:preview_len])
            if len(content) > preview_len:
                output_lines.append("...")

        output_lines.append("")
        output_lines.append("-" * SEPARATOR_WIDTH)
        output_lines.append("")

    return '\n'.join(output_lines)


def main():
    parser = argparse.ArgumentParser(description="epub 小说解析器")
    parser.add_argument("--file", required=True, help="epub 文件路径")
    parser.add_argument("--output", required=True, help="输出文件路径")
    parser.add_argument(
        "--mode",
        choices=["full", "sample", "preview"],
        default="preview",
        help="输出模式：full（全部内容）/ sample（每章前 N 字）/ preview（预览摘要，默认）",
    )
    parser.add_argument(
        "--preview-length",
        type=int,
        default=DEFAULT_PREVIEW_LENGTH,
        help=f"预览/采样模式下每章显示字数（默认：{DEFAULT_PREVIEW_LENGTH}）",
    )

    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"错误：文件不存在 {file_path}", file=sys.stderr)
        sys.exit(1)

    if not file_path.suffix.lower() == '.epub':
        print("错误：文件格式不正确，需要 .epub 文件", file=sys.stderr)
        sys.exit(1)

    file_size = file_path.stat().st_size
    if file_size > MAX_EPUB_SIZE:
        print(
            f"错误：文件过大（超过{MAX_EPUB_SIZE // 1024 // 1024}MB），"
            f"可能存在安全风险",
            file=sys.stderr,
        )
        sys.exit(1)

    # mimetype 验证
    try:
        _validate_mimetype(file_path)
    except ValueError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)

    # Zip Bomb 防护
    try:
        _check_zip_bomb(file_path)
    except ValueError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)

    # epub 容器描述验证
    try:
        with zipfile.ZipFile(str(file_path), 'r') as zf:
            if 'META-INF/container.xml' not in zf.namelist():
                print("错误：不是有效的 epub 文件（缺少容器描述）", file=sys.stderr)
                sys.exit(1)
    except zipfile.BadZipFile:
        print("错误：文件不是有效的 ZIP/epub 格式", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output)

    # 输出路径安全校验
    try:
        _validate_output_path(output_path)
    except ValueError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        chapters = parse_epub(file_path)
        if not chapters:
            print("警告：未识别到任何章节", file=sys.stderr)

        result = format_output(
            chapters,
            file_path.name,
            mode=args.mode,
            preview_length=args.preview_length,
        )
        output_path.write_text(result, encoding='utf-8')
        print(f"解析完成：{output_path}")
    except RuntimeError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)
    except (UnicodeDecodeError, AttributeError) as e:
        print(f"错误：epub 内容解析异常 - {e}", file=sys.stderr)
        sys.exit(1)
    except (epub.EpubException, zipfile.BadZipFile) as e:
        print(f"错误：epub 文件格式异常 - {e}", file=sys.stderr)
        sys.exit(1)
    except (OSError, PermissionError) as e:
        print(f"错误：文件读写失败 - {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"错误：未知异常 - {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
