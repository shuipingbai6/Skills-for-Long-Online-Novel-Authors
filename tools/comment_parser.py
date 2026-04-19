#!/usr/bin/env python3
"""
评论数据解析器

支持解析起点、晋江、番茄等平台的评论导出文件。

用法：
    python comment_parser.py --file comments.txt --platform 起点 --output /tmp/comment_out.txt
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import TypedDict


MAX_FILE_SIZE = 50 * 1024 * 1024
MAX_COMMENT_COUNT = 100_000
SEPARATOR_WIDTH = 60

# 正则：起点日期（含时分）
QIDIAN_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}')
# 正则：作者回复标记（起点/番茄）
AUTHOR_REPLY_RE = re.compile(r'^作者回复[：:]')
# 正则：晋江方括号用户名
JINJIANG_BRACKET_RE = re.compile(r'^\[(.*?)\]')
# 正则：番茄楼层
FANQIE_FLOOR_RE = re.compile(r'^(\d+楼)')

# 晋江需要跳过的方括号标记（非用户名）
JINJIANG_MARKERS = frozenset({'精华', '置顶', '加精', '锁', '删除', '审核中'})


class Comment(TypedDict, total=False):
    """评论条目类型定义"""
    time: str
    user: str
    content: str
    floor: str
    is_author: bool
    reply_to: str


def parse_qidian_comments(text: str) -> list[Comment]:
    """解析起点中文网评论格式"""
    comments: list[Comment] = []
    current_comment: Comment = {}

    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue

        # 优先检测作者回复
        if AUTHOR_REPLY_RE.match(line):
            # 将作者回复作为独立条目
            if current_comment:
                comments.append(current_comment)
                prev_user = current_comment.get('user', '')
                current_comment = {}
            else:
                prev_user = ''
            reply_content = AUTHOR_REPLY_RE.sub('', line).strip()
            current_comment = {
                'user': '作者',
                'content': reply_content,
                'is_author': True,
                'reply_to': prev_user,
            }
            continue

        if QIDIAN_DATE_RE.match(line):
            if current_comment:
                comments.append(current_comment)
            current_comment = {'time': line}
        elif current_comment and '：' in line and 'content' not in current_comment:
            parts = line.split('：', 1)
            if len(parts) == 2:
                current_comment['user'] = parts[0]
                current_comment['content'] = parts[1]
        elif 'content' in current_comment:
            current_comment['content'] += '\n' + line

    if current_comment:
        comments.append(current_comment)

    return comments


def parse_jinjiang_comments(text: str) -> list[Comment]:
    """解析晋江文学城评论格式"""
    comments: list[Comment] = []
    current_comment: Comment = {}

    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue

        match = JINJIANG_BRACKET_RE.match(line)
        if match:
            bracket_content = match.group(1)
            # 跳过非用户名标记（如 [精华]、[置顶] 等）
            if bracket_content in JINJIANG_MARKERS:
                if 'content' in current_comment:
                    current_comment['content'] += '\n' + line
                continue

            if current_comment:
                comments.append(current_comment)
            user_name = bracket_content
            rest_content = line[match.end():].strip()
            current_comment = {'user': user_name, 'content': rest_content}

            # 作者回复关系
            if user_name == '作者':
                prev_user = comments[-1].get('user', '') if comments else ''
                current_comment['is_author'] = True
                if prev_user:
                    current_comment['reply_to'] = prev_user
        elif 'content' in current_comment:
            current_comment['content'] += '\n' + line

    if current_comment:
        comments.append(current_comment)

    return comments


def parse_fanqie_comments(text: str) -> list[Comment]:
    """解析番茄小说评论格式"""
    comments: list[Comment] = []
    current_comment: Comment = {}

    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue

        # 优先检测作者回复
        if AUTHOR_REPLY_RE.match(line):
            if current_comment:
                comments.append(current_comment)
                prev_user = current_comment.get('user', '')
                current_comment = {}
            else:
                prev_user = ''
            reply_content = AUTHOR_REPLY_RE.sub('', line).strip()
            current_comment = {
                'user': '作者',
                'content': reply_content,
                'is_author': True,
                'reply_to': prev_user,
            }
            continue

        floor_match = FANQIE_FLOOR_RE.match(line)
        if floor_match:
            if current_comment:
                comments.append(current_comment)
            current_comment = {'floor': floor_match.group(1), 'content': ''}
            rest = line[floor_match.end():].strip()
            if '：' in rest:
                parts = rest.split('：', 1)
                if len(parts) == 2:
                    current_comment['user'] = parts[0]
                    current_comment['content'] = parts[1]
        elif current_comment and '：' in line and 'user' not in current_comment:
            parts = line.split('：', 1)
            if len(parts) == 2:
                current_comment['user'] = parts[0]
                current_comment['content'] = parts[1]
        elif 'content' in current_comment:
            current_comment['content'] += '\n' + line

    if current_comment:
        comments.append(current_comment)

    return comments


def parse_json_comments(text: str) -> list[Comment]:
    """解析 JSON 格式的评论数据"""
    try:
        data = json.loads(text)
        if isinstance(data, list):
            result = data
        elif isinstance(data, dict) and 'comments' in data:
            result = data['comments']
        else:
            return []
        # DoS 防护：限制评论数量
        if len(result) > MAX_COMMENT_COUNT:
            print(f"警告：评论数量({len(result)})超过上限({MAX_COMMENT_COUNT})，仅保留前{MAX_COMMENT_COUNT}条",
                  file=sys.stderr)
            result = result[:MAX_COMMENT_COUNT]
        return result
    except json.JSONDecodeError:
        pass
    except RecursionError:
        print("错误：JSON 数据嵌套层级过深", file=sys.stderr)
    return []


def format_output(comments: list[Comment], platform: str, file_name: str) -> str:
    """格式化输出内容"""
    output_lines = []
    output_lines.append(f"评论解析结果：{file_name}")
    output_lines.append(f"平台：{platform}")
    output_lines.append(f"评论数：{len(comments)}")
    output_lines.append("")
    output_lines.append("=" * SEPARATOR_WIDTH)
    output_lines.append("")

    for i, comment in enumerate(comments):
        output_lines.append(f"### 评论 {i + 1}")

        if 'time' in comment:
            output_lines.append(f"时间：{comment['time']}")
        if 'user' in comment:
            output_lines.append(f"用户：{comment['user']}")
        if 'floor' in comment:
            output_lines.append(f"楼层：{comment['floor']}")
        if comment.get('is_author'):
            output_lines.append("（作者回复）")
        if 'reply_to' in comment and comment['reply_to']:
            output_lines.append(f"回复：{comment['reply_to']}")

        content = comment.get('content', comment.get('text', ''))
        output_lines.append(f"内容：{content}")
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


def validate_output_path(output_path: Path) -> None:
    """校验输出路径在项目目录内，防止路径遍历"""
    try:
        project_root = Path.cwd().resolve()
        resolved = output_path.resolve()
        resolved.relative_to(project_root)
    except ValueError:
        print(f"错误：输出路径必须在项目目录内：{output_path}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="评论数据解析器")
    parser.add_argument("--file", required=True, help="评论文件路径")
    parser.add_argument("--platform", required=True, choices=['起点', '晋江', '番茄', 'json'],
                       help="平台类型")
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
    validate_output_path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        text = read_file_with_fallback(file_path)

        if args.platform == '起点':
            comments = parse_qidian_comments(text)
        elif args.platform == '晋江':
            comments = parse_jinjiang_comments(text)
        elif args.platform == '番茄':
            comments = parse_fanqie_comments(text)
        elif args.platform == 'json':
            comments = parse_json_comments(text)
        else:
            comments = []

        # 空文件处理：未识别到评论时不生成空输出文件
        if not comments:
            print("警告：未识别到任何评论，不生成输出文件", file=sys.stderr)
            sys.exit(0)

        # DoS 防护：限制评论数量（非 JSON 格式也需要）
        if len(comments) > MAX_COMMENT_COUNT:
            print(f"警告：评论数量({len(comments)})超过上限({MAX_COMMENT_COUNT})，仅保留前{MAX_COMMENT_COUNT}条",
                  file=sys.stderr)
            comments = comments[:MAX_COMMENT_COUNT]

        result = format_output(comments, args.platform, file_path.name)
        output_path.write_text(result, encoding='utf-8')
        print(f"解析完成：{output_path}")
    except RuntimeError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError) as e:
        print(f"错误：解析失败 - {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
