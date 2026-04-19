#!/usr/bin/env python3
"""
微信公众号文章解析器

支持解析手动导出的公众号文章。

用法：
    python wechat_parser.py --file article.html --output /tmp/wechat_out.txt
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Optional, TypedDict

MAX_FILE_SIZE = 10 * 1024 * 1024
SEPARATOR_WIDTH = 60

try:
    from bs4 import BeautifulSoup
    import lxml  # noqa: F401
    _DEPS_AVAILABLE = True
except ImportError:
    _DEPS_AVAILABLE = False


class WeChatArticle(TypedDict):
    """微信公众号文章结构类型"""
    title: str
    author: str
    time: str
    content: str


def _check_deps() -> None:
    """检查依赖库是否可用，不可用时抛出 RuntimeError"""
    if not _DEPS_AVAILABLE:
        raise RuntimeError("缺少依赖库，请安装：pip install beautifulsoup4 lxml")


def _is_time_text(text: str) -> bool:
    """基于内容特征判断文本是否为时间字段

    匹配规则：
      - 4位数字开头的日期格式（2024年1月1日、2024-01-01 等）
      - "刚刚"
      - "x分钟前"、"x小时前"、"x天前"
      - 上午/下午 + 时间
    """
    time_patterns = [
        r'^\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?\s*\d{0,2}[:时]?\d{0,2}',
        r'^刚刚$',
        r'^\d+\s*分钟前$',
        r'^\d+\s*小时前$',
        r'^\d+\s*天前$',
        r'^[上下]午\s*\d{1,2}[:时]\d{1,2}',
    ]
    return any(re.match(p, text.strip()) for p in time_patterns)


def is_html_content(content: str) -> bool:
    """基于内容特征判断是否为 HTML

    不仅基于扩展名，还检查内容中是否包含 HTML 特征标签。
    """
    stripped = content.lstrip()[:500].lower()
    html_markers = ['<!doctype', '<html', '<head', '<body', '<div', '<span', '<p>', '<meta']
    return any(marker in stripped for marker in html_markers)


def parse_wechat_html(html_content: str) -> WeChatArticle:
    """解析 HTML 格式的公众号文章"""
    _check_deps()
    soup = BeautifulSoup(html_content, 'lxml')

    article: WeChatArticle = {
        'title': '',
        'author': '',
        'time': '',
        'content': ''
    }

    title_tag = soup.find('h1', class_='rich_media_title') or soup.find('h1')
    if title_tag:
        article['title'] = title_tag.get_text(strip=True)

    # 基于内容特征区分作者和时间，而非按位置索引
    author_tag = soup.find('a', class_='rich_media_meta_link')
    if author_tag:
        article['author'] = author_tag.get_text(strip=True)

    candidates = soup.find_all('span', class_='rich_media_meta rich_media_meta_text')
    for candidate in candidates:
        text = candidate.get_text(strip=True)
        if not text:
            continue
        if _is_time_text(text):
            if not article['time']:
                article['time'] = text
        else:
            if not article['author']:
                article['author'] = text

    time_tag = soup.find('em', id='publish_time')
    if time_tag:
        article['time'] = time_tag.get_text(strip=True)

    content_tag = soup.find('div', id='js_content') or soup.find('div', class_='rich_media_content')
    if content_tag:
        for tag in content_tag(["script", "style", "noscript"]):
            tag.decompose()

        # 在 get_text 前处理 img 和 a 标签，保留图片和链接信息
        for img in content_tag.find_all('img'):
            alt = img.get('alt', '')
            src = img.get('data-src') or img.get('src', '')
            if src:
                replacement = f"[图片{(':' + alt) if alt else ''}]({src})"
                img.replace_with(replacement)
            elif alt:
                img.replace_with(f"[图片:{alt}]")

        for a in content_tag.find_all('a'):
            href = a.get('href', '')
            link_text = a.get_text(strip=True)
            if href and link_text:
                replacement = f"[链接:{link_text}]({href})"
                a.replace_with(replacement)
            elif href:
                a.replace_with(f"[链接]({href})")

        content = content_tag.get_text(separator='\n')
        content = '\n'.join(line.strip() for line in content.split('\n') if line.strip())
        article['content'] = content

    return article


def parse_wechat_text(text: str) -> WeChatArticle:
    """解析文本格式的公众号文章"""
    lines = text.split('\n')

    article: WeChatArticle = {
        'title': '',
        'author': '',
        'time': '',
        'content': ''
    }

    # 使用手动索引代替 lines.pop(0) 避免 O(n^2)
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    lines = lines[start:]

    if lines:
        article['title'] = lines[0].strip()

    content_lines: List[str] = []
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue

        # 扩展支持"原创"、"来自"等前缀
        if re.match(r'^(作者|原创|来自)[：:]', line):
            article['author'] = re.sub(r'^(作者|原创|来自)[：:]\s*', '', line)
        elif _is_time_text(line):
            article['time'] = line
        else:
            content_lines.append(line)

    article['content'] = '\n'.join(content_lines)

    return article


def format_output(article: WeChatArticle, file_name: str) -> str:
    """格式化输出内容"""
    output_lines: List[str] = []
    output_lines.append(f"公众号文章解析结果：{file_name}")
    output_lines.append("")
    output_lines.append("=" * SEPARATOR_WIDTH)
    output_lines.append("")

    if article.get('title'):
        output_lines.append(f"标题：{article['title']}")
    if article.get('author'):
        output_lines.append(f"作者：{article['author']}")
    if article.get('time'):
        output_lines.append(f"时间：{article['time']}")

    if article.get('content'):
        output_lines.append("")
        output_lines.append("正文：")
        output_lines.append(article['content'])
        output_lines.append("")

    return '\n'.join(output_lines)


def read_file_with_fallback(path: Path) -> str:
    """尝试多种编码读取文件"""
    for encoding in ('utf-8-sig', 'utf-8', 'gb18030', 'gbk'):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"无法以支持的编码读取文件：{path}")


def _validate_output_path(output_path: Path) -> None:
    """校验输出路径在项目目录内，防止路径穿越"""
    try:
        resolved = output_path.resolve()
        cwd_resolved = Path.cwd().resolve()
        if not str(resolved).startswith(str(cwd_resolved)):
            raise RuntimeError(f"输出路径不在项目目录内：{resolved}")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"输出路径校验失败：{e}")


def main():
    parser = argparse.ArgumentParser(description="微信公众号文章解析器")
    parser.add_argument("--file", required=True, help="文章文件路径")
    parser.add_argument("--output", required=True, help="输出文件路径")

    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"错误：文件不存在 {file_path}", file=sys.stderr)
        sys.exit(1)

    file_size = file_path.stat().st_size
    if file_size > MAX_FILE_SIZE:
        print(f"错误：文件过大（超过{MAX_FILE_SIZE // 1024 // 1024}MB）", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output)

    # 输出路径安全校验
    try:
        _validate_output_path(output_path)
    except RuntimeError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        content = read_file_with_fallback(file_path)

        # 不仅基于扩展名，还基于内容特征判断是否为 HTML
        if file_path.suffix.lower() in ('.html', '.htm') or is_html_content(content):
            article = parse_wechat_html(content)
        else:
            article = parse_wechat_text(content)

        if not article.get('content'):
            print("警告：未识别到文章内容", file=sys.stderr)

        result = format_output(article, file_path.name)
        output_path.write_text(result, encoding='utf-8')
        print(f"解析完成：{output_path}")
    except RuntimeError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)
    except (OSError, PermissionError) as e:
        print(f"错误：文件读写失败 - {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
