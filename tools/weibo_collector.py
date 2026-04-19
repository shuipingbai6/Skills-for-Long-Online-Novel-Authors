#!/usr/bin/env python3
"""
微博内容采集器

支持解析手动导出的微博内容。

用法：
    python weibo_collector.py --file weibo_export.txt --output /tmp/weibo_out.txt
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

MAX_FILE_SIZE = 100 * 1024 * 1024
SEPARATOR_WIDTH = 60

DATE_RE = re.compile(r'^(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?)\s*(.*)')
HTML_TAG_RE = re.compile(r'<[^>]+>')


def parse_weibo_text(text: str) -> List[Dict[str, Any]]:
    """解析文本格式的微博内容"""
    weibos: List[Dict[str, Any]] = []

    current_weibo: Dict[str, Any] = {}
    content_lines: list[str] = []

    for line in text.split('\n'):
        stripped = line.strip()
        if not stripped:
            # 空行保留为段落分隔符
            if current_weibo and content_lines:
                content_lines.append('')
            continue

        m = DATE_RE.match(stripped)
        if m:
            if current_weibo:
                current_weibo['content'] = '\n'.join(content_lines)
                weibos.append(current_weibo)
            current_weibo = {'time': m.group(1)}
            rest = m.group(2).strip()
            content_lines = [rest] if rest else []
        elif current_weibo:
            content_lines.append(stripped)
        else:
            continue

    if current_weibo:
        current_weibo['content'] = '\n'.join(content_lines)
        weibos.append(current_weibo)

    return weibos


def parse_weibo_json(text: str) -> List[Dict[str, Any]]:
    """解析 JSON 格式的微博内容"""
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and 'weibos' in data:
            weibos = data['weibos']
            return weibos if isinstance(weibos, list) else []
        elif isinstance(data, dict) and 'statuses' in data:
            statuses = data['statuses']
            return statuses if isinstance(statuses, list) else []
    except json.JSONDecodeError:
        pass
    return []


def _safe_int(value: Any) -> int:
    """安全地将互动数据转换为整数，处理字符串类型如 '1万'、'10万+' 等"""
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        s = value.strip().rstrip('+')
        if s.endswith('万'):
            try:
                return int(float(s[:-1]) * 10000)
            except (ValueError, OverflowError):
                return 0
        try:
            return int(s)
        except ValueError:
            return 0
    return 0


def _normalize_time(time_str: str) -> str:
    """将微博 API 时间格式统一为 ISO 格式"""
    if not time_str or not isinstance(time_str, str):
        return ''
    time_str = time_str.strip()
    # 尝试常见微博 API 时间格式
    formats = [
        '%a %b %d %H:%M:%S %z %Y',   # Tue May 31 17:46:55 +0800 2011
        '%Y-%m-%d %H:%M:%S',          # 2024-01-15 12:30:00
        '%Y-%m-%dT%H:%M:%S',          # 2024-01-15T12:30:00
        '%Y-%m-%dT%H:%M:%S%z',        # 2024-01-15T12:30:00+0800
        '%Y/%m/%d %H:%M',             # 2024/01/15 12:30
        '%Y年%m月%d日 %H:%M',          # 2024年01月15日 12:30
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(time_str, fmt)
            return dt.isoformat()
        except ValueError:
            continue
    # 已经是 ISO 格式或无法解析，原样返回
    return time_str


def normalize_weibo(weibo: Dict[str, Any]) -> Dict[str, Any]:
    """将不同格式的微博数据统一为标准结构"""
    content = weibo.get('content', weibo.get('text', weibo.get('full_text', '')))
    if not isinstance(content, str):
        content = str(content) if content is not None else ''
    content = HTML_TAG_RE.sub('', content)
    content = html.unescape(content)

    result: Dict[str, Any] = {
        'time': _normalize_time(weibo.get('time', weibo.get('created_at', ''))),
        'content': content,
        'reposts': _safe_int(weibo.get('reposts_count', 0)),
        'comments': _safe_int(weibo.get('comments_count', 0)),
        'attitudes': _safe_int(weibo.get('attitudes_count', 0)),
    }

    # 处理转发微博
    retweeted = weibo.get('retweeted_status')
    if retweeted and isinstance(retweeted, dict):
        retweeted_content = retweeted.get('content', retweeted.get('text', retweeted.get('full_text', '')))
        if not isinstance(retweeted_content, str):
            retweeted_content = str(retweeted_content) if retweeted_content is not None else ''
        retweeted_content = HTML_TAG_RE.sub('', retweeted_content)
        retweeted_content = html.unescape(retweeted_content)
        result['retweeted'] = {
            'content': retweeted_content,
            'user': retweeted.get('user', {}).get('screen_name', '') if isinstance(retweeted.get('user'), dict) else '',
        }

    return result


def format_output(weibos: List[Dict[str, Any]], file_name: str) -> str:
    """格式化输出内容"""
    normalized = [normalize_weibo(w) for w in weibos]

    output_lines = []
    output_lines.append(f"微博解析结果：{file_name}")
    output_lines.append(f"微博数：{len(normalized)}")
    output_lines.append("")
    output_lines.append("=" * SEPARATOR_WIDTH)
    output_lines.append("")

    for i, weibo in enumerate(normalized):
        output_lines.append(f"### 微博 {i + 1}")

        if weibo['time']:
            output_lines.append(f"时间：{weibo['time']}")

        output_lines.append(f"内容：{weibo['content']}")

        # 转发微博
        if 'retweeted' in weibo and weibo['retweeted']:
            retweeted = weibo['retweeted']
            user_info = f"@{retweeted['user']}" if retweeted.get('user') else ''
            output_lines.append(f"转发自：{user_info}")
            output_lines.append(f"原文：{retweeted['content']}")

        if weibo['reposts'] or weibo['comments'] or weibo['attitudes']:
            output_lines.append(f"转发：{weibo['reposts']}  "
                              f"评论：{weibo['comments']}  "
                              f"点赞：{weibo['attitudes']}")

        output_lines.append("")
        output_lines.append("-" * SEPARATOR_WIDTH)
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


def main():
    parser = argparse.ArgumentParser(description="微博内容采集器")
    parser.add_argument("--file", required=True, help="微博导出文件路径")
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
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        text = read_file_with_fallback(file_path)

        weibos = parse_weibo_json(text)
        if not weibos:
            weibos = parse_weibo_text(text)

        if not weibos:
            print("警告：未识别到任何微博内容", file=sys.stderr)

        result = format_output(weibos, file_path.name)
        output_path.write_text(result, encoding='utf-8')
        print(f"解析完成：{output_path}")
    except RuntimeError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"错误：解析失败 - {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
