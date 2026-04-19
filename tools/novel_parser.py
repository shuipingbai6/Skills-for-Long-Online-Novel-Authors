#!/usr/bin/env python3
"""
小说文本解析器

支持解析 txt 格式的小说文件，自动识别章节结构。

用法：
    python novel_parser.py --file novel.txt --output /tmp/novel_out.txt
    python novel_parser.py --file novel.txt --output /tmp/novel_out.txt --encoding utf-8
    python novel_parser.py --file novel.txt --output /tmp/novel_out.txt --mode sample
"""

from __future__ import annotations

import re
import argparse
import sys
from pathlib import Path

MAX_FILE_SIZE = 100 * 1024 * 1024
MIN_CHAPTER_MATCHES = 3
DEFAULT_TARGET_CHAPTER_LENGTH = 3000
PREVIEW_LENGTH = 500
SEPARATOR_WIDTH = 60

CHAPTER_PATTERNS = [
    (r'^第[零一二三四五六七八九十百千万]+[章节卷篇部]', 10),
    (r'^第\d+[章节卷篇部]', 9),
    (r'^Chapter\s+\d+', 8),
    (r'^Part\s+\d+', 6),
    (r'^Section\s+\d+', 5),
    (r'^【[一二三四五六七八九十\d]+】', 7),
    (r'^[一二三四五六七八九十]+、', 4),
    (r'^\d+\.\d+', 2),
    (r'^\d+\.', 1),
]

COMPILED_CHAPTER_PATTERNS = [
    (re.compile(pattern, re.MULTILINE), weight)
    for pattern, weight in CHAPTER_PATTERNS
]

AD_URL_RE = re.compile(r'(?:https?://|www\.)\S+')
AD_KEYWORD_RE = re.compile(r'(广告|推广|赞助|点击|下载|APP|关注|公众号)')
SHORT_NOISE_RE = re.compile(r'^[\d\-*#@!?\。，、]+$')

ZERO_WIDTH_CHARS_RE = re.compile(
    r'[\u200b\u200c\u200d\ufeff\u00ad\u200e\u200f\u202a-\u202e]'
)


def _is_ad_line(line: str) -> bool:
    """判断一行是否为广告行：要求同时出现URL和广告关键词，或出现2个以上广告关键词"""
    has_url = bool(AD_URL_RE.search(line))
    keyword_hits = AD_KEYWORD_RE.findall(line)
    if has_url and keyword_hits:
        return True
    if len(keyword_hits) >= 2:
        return True
    return False


def detect_chapters(text: str) -> list[tuple[str, int, int]]:
    """
    识别文本中的章节结构

    Returns:
        list of (章节标题, 起始位置, 结束位置)
    """
    best_pattern = None
    best_matches: list[re.Match] = []
    best_score = 0

    for compiled_pattern, weight in COMPILED_CHAPTER_PATTERNS:
        matches = list(compiled_pattern.finditer(text))
        score = len(matches) * weight
        if score > best_score:
            best_score = score
            best_pattern = compiled_pattern
            best_matches = matches

    if best_score >= MIN_CHAPTER_MATCHES and len(best_matches) >= MIN_CHAPTER_MATCHES:
        chapters = []
        for i, match in enumerate(best_matches):
            # 从匹配位置取到行尾作为完整标题
            line_end = text.find('\n', match.start())
            if line_end == -1:
                line_end = len(text)
            title = text[match.start():line_end].strip()
            # 章节内容从下一行开始
            content_start = line_end + 1 if line_end < len(text) else line_end
            end = best_matches[i + 1].start() if i + 1 < len(best_matches) else len(text)
            chapters.append((title, content_start, end))
        return chapters

    return split_by_paragraph_length(text)


def split_by_paragraph_length(text: str, target_length: int = DEFAULT_TARGET_CHAPTER_LENGTH) -> list[tuple[str, int, int]]:
    """
    当无法识别章节标记时，按段落长度分割

    Args:
        text: 原始文本
        target_length: 目标章节长度（字数）
    """
    # 使用捕获组保留分隔符，精确追踪位置
    parts = re.split(r'(\n{2,})', text)
    chapters: list[tuple[str, int, int]] = []
    current_chapter: list[str] = []
    current_length = 0
    offset = 0
    chapter_start = 0

    for part in parts:
        # 分隔符部分（偶数索引为文本，奇数索引为分隔符）
        is_separator = re.match(r'\n{2,}', part) is not None

        if is_separator:
            offset += len(part)
            continue

        para_length = len(part)
        para_start = offset
        para_end = offset + para_length

        if current_length + para_length > target_length and current_chapter:
            chapter_end = para_start
            chapters.append((f"第{len(chapters) + 1}节", chapter_start, chapter_end))

            chapter_start = para_start
            current_chapter = [part]
            current_length = para_length
        else:
            if not current_chapter:
                chapter_start = para_start
            current_chapter.append(part)
            current_length += para_length

        offset = para_end

    if current_chapter:
        chapter_end = len(text)
        chapters.append((f"第{len(chapters) + 1}节", chapter_start, chapter_end))

    return chapters


def clean_text(text: str) -> str:
    """清洗文本，去除广告、乱码等"""
    # 统一行尾
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # 清理零宽字符和全角空格
    text = ZERO_WIDTH_CHARS_RE.sub('', text)
    text = text.replace('\u3000', ' ')

    lines = text.split('\n')
    cleaned_lines: list[str] = []
    prev_empty = False

    for line in lines:
        line = line.strip()
        if not line:
            if not prev_empty and cleaned_lines:
                cleaned_lines.append('')
                prev_empty = True
            continue

        prev_empty = False

        if _is_ad_line(line):
            continue

        if len(line) < 5 and SHORT_NOISE_RE.match(line):
            continue

        cleaned_lines.append(line)

    return '\n'.join(cleaned_lines)


def _sample_content(content: str) -> str:
    """采样模式：每章取首800字+中1500字+尾800字"""
    head_len = 800
    mid_len = 1500
    tail_len = 800
    total = len(content)

    if total <= head_len + mid_len + tail_len:
        return content

    mid_start = (total - mid_len) // 2
    parts = []
    parts.append(content[:head_len])
    parts.append(f"\n... [省略 {mid_start - head_len} 字] ...\n")
    parts.append(content[mid_start:mid_start + mid_len])
    parts.append(f"\n... [省略 {total - mid_start - mid_len - tail_len} 字] ...\n")
    parts.append(content[-tail_len:])
    return ''.join(parts)


def _format_chapter_content(content: str, mode: str) -> str:
    """根据输出模式格式化章节内容"""
    if mode == 'full':
        return content
    elif mode == 'sample':
        return _sample_content(content)
    else:  # preview
        preview_len = min(PREVIEW_LENGTH, len(content))
        result = content[:preview_len]
        if len(content) > preview_len:
            result += '\n...'
        return result


def parse_novel(file_path: Path, encoding: str = 'utf-8-sig', mode: str = 'preview') -> str:
    """解析小说文件，返回格式化的章节内容"""

    # 文件存在性检查
    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在：{file_path}")

    # 文件类型检查
    if not file_path.is_file():
        raise ValueError(f"路径不是文件：{file_path}")

    suffix = file_path.suffix.lower()
    if suffix not in ('.txt', '.text'):
        raise ValueError(f"不支持的文件类型：{suffix}，仅支持 .txt 文件")

    file_size = file_path.stat().st_size
    if file_size > MAX_FILE_SIZE:
        raise ValueError(f"文件过大（超过{MAX_FILE_SIZE // 1024 // 1024}MB）：{file_path}")

    last_err = None
    try:
        text = file_path.read_text(encoding=encoding)
    except UnicodeDecodeError as e:
        last_err = e
        for enc in ['utf-8-sig', 'gb18030', 'gbk', 'big5', 'utf-16']:
            try:
                text = file_path.read_text(encoding=enc)
                last_err = None
                break
            except UnicodeDecodeError as enc_err:
                last_err = enc_err
                continue
        if last_err is not None:
            raise ValueError(f"无法识别文件编码：{file_path}") from last_err

    text = clean_text(text)

    chapters = detect_chapters(text)

    output_lines = []
    output_lines.append(f"小说解析结果：{file_path.name}")
    output_lines.append(f"总字数：{len(text)}")
    output_lines.append(f"识别章节：{len(chapters)} 章")
    output_lines.append(f"输出模式：{mode}")
    output_lines.append("")
    output_lines.append("=" * SEPARATOR_WIDTH)
    output_lines.append("")

    if not chapters:
        output_lines.append("未识别到章节结构，请检查文件内容格式")
    else:
        for i, (title, start, end) in enumerate(chapters):
            content = text[start:end].strip()
            word_count = len(content)

            output_lines.append(f"## {title}")
            output_lines.append(f"字数：{word_count}")
            output_lines.append("")

            formatted = _format_chapter_content(content, mode)
            if mode == 'preview':
                output_lines.append("内容预览：")
            elif mode == 'sample':
                output_lines.append("内容采样：")
            else:
                output_lines.append("内容全文：")
            output_lines.append(formatted)
            output_lines.append("")
            output_lines.append("-" * SEPARATOR_WIDTH)
            output_lines.append("")

    return '\n'.join(output_lines)


def main():
    parser = argparse.ArgumentParser(description="小说文本解析器")
    parser.add_argument("--file", required=True, help="小说文件路径")
    parser.add_argument("--output", required=True, help="输出文件路径")
    parser.add_argument("--encoding", default="utf-8-sig", help="文件编码（默认：utf-8-sig）")
    parser.add_argument(
        "--mode",
        choices=["full", "sample", "preview"],
        default="preview",
        help="输出模式：full=全文, sample=首800+中1500+尾800采样, preview=500字预览（默认：preview）",
    )

    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"错误：文件不存在 {file_path}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        result = parse_novel(file_path, args.encoding, args.mode)
        output_path.write_text(result, encoding='utf-8')
        print(f"解析完成：{output_path}")
    except (ValueError, UnicodeDecodeError, OSError) as e:
        print(f"错误：解析失败 - {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
