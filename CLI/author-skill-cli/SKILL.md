---
name: "author-skill-cli"
description: "网文作者蒸馏系统 CLI 工具。当用户需要解析小说/评论、蒸馏作者风格、管理 Skill 文件、迭代进化、收敛验证、版本管理时触发。关键词：蒸馏、解析小说、评论解析、作者风格、skill管理、进化、收敛、版本回滚"
---

# Author Skill CLI

网文作者蒸馏系统的命令行工具，用于将网文作者的作品、评论、社交媒体内容蒸馏为可复用的 AI Skill 文件。

## 工具调用方式

统一使用 `author-skill-cli` 命令调用，要求该命令已在系统 PATH 中可用。

**安装方式（二选一）**：
- **pip 安装**：`pip install .` 或 `pip install -e .`（开发模式），安装后 `author-skill-cli` 自动加入 PATH
- **单文件 exe**：将 `author-skill-cli.exe` 放入任意 PATH 目录（如 `C:\Tools\`），或将其所在目录加入 PATH

**验证安装**：执行 `author-skill-cli --version`，应输出 `author-skill-cli, version 0.1.0 build by jx666`

**若命令不可用**：提示用户先安装 author-skill-cli，或确认 exe 已加入 PATH。

## 全局参数

所有子命令都支持以下全局参数（放在子命令之前）：

| 参数 | 说明 |
|------|------|
| `--base-dir PATH` | 指定 authors 目录（默认：`./authors`） |
| `--json` | JSON 输出模式，结构化输出供程序解析 |
| `--quiet` | 静默模式，抑制进度信息 |
| `--version` | 显示版本号 |

**重要**：`--base-dir` 必须位于当前工作目录或用户目录下，否则报错。

## 子命令完整参考

### 1. parse — 原材料解析

#### parse novel — 解析 txt 小说
```bash
author-skill-cli [--json] [--base-dir DIR] parse novel --file <小说.txt> [--mode full|sample|preview] [--encoding utf-8-sig]
```
- `--mode`：`full`（全文）、`sample`（首800+中1500+尾800字采样）、`preview`（前500字预览，默认）

#### parse epub — 解析 epub 小说
```bash
author-skill-cli [--json] parse epub --file <小说.epub> [--mode preview] [--preview-length 500] [--metadata-only]
```
- `--metadata-only`：仅提取元数据（书名、作者、出版社等）

#### parse comments — 解析评论
```bash
author-skill-cli [--json] parse comments --file <评论文件> --platform 起点|晋江|番茄|json
```

#### parse wechat — 解析公众号文章
```bash
author-skill-cli [--json] parse wechat --file <文章.html|.txt>
```
- 自动检测 HTML/纯文本格式

#### parse weibo — 解析微博内容
```bash
author-skill-cli [--json] parse weibo --file <微博导出文件>
```
- 自动检测 JSON/纯文本格式

### 2. distill — 蒸馏编排

#### distill prepare — 收集原材料 + 生成分析 Prompt
```bash
author-skill-cli [--json] [--base-dir DIR] distill prepare \
  --name "作者笔名" \
  [--slug author-slug] \
  [--novels 小说1.txt 小说2.epub] \
  [--comments 评论1.txt] \
  [--social 微博1.json 公众号1.html] \
  [--platform 起点|晋江|番茄|json] \
  [--mode sample] \
  [--max-chars 200000] \
  [--platform-level LV5] \
  [--masterpiece "代表作"] \
  [--gender 男|女]
```
- `--slug`：不指定时自动用 pypinyin 从笔名生成
- 输出：`<base-dir>/<slug>/knowledge/` 下的 `writing_analysis_prompt.md` 和 `persona_analysis_prompt.md`

#### distill create — 创建 Skill 文件
```bash
author-skill-cli [--json] [--base-dir DIR] distill create \
  --slug author-slug \
  --name "作者笔名" \
  --writing writing.md \
  --persona author_persona.md \
  [--meta meta.json]
```
- `--writing` 和 `--persona` 是 LLM 分析后的输出文件
- 创建目录结构：`<base-dir>/<slug>/`，含 `writing.md`、`author_persona.md`、`SKILL.md`、`meta.json`、`writing_skill.md`、`persona_skill.md`

### 3. skill — Skill 管理

#### skill list — 列出所有作者
```bash
author-skill-cli [--json] [--base-dir DIR] skill list
```

#### skill show — 查看作者详情
```bash
author-skill-cli [--json] [--base-dir DIR] skill show --slug author-slug
```

#### skill update — 更新 Skill
```bash
author-skill-cli [--json] [--base-dir DIR] skill update \
  --slug author-slug \
  [--writing-patch patch.md] \
  [--persona-patch patch.md] \
  [--writing-full new_writing.md] \
  [--persona-full new_persona.md]
```
- patch 模式：追加内容到现有文件末尾
- full 模式：完整替换文件内容
- 自动版本递增（v1 → v2），旧版本存入 `versions/` 目录

#### skill correct — 对话纠正
```bash
author-skill-cli [--json] [--base-dir DIR] skill correct \
  --slug author-slug \
  --wrong "不应该出现的行为" \
  --correct "应该出现的行为" \
  [--scene "场景标签"]
```
- 在 `author_persona.md` 的 Correction 记录区域追加纠正条目

#### skill regenerate — 重新生成 SKILL.md
```bash
author-skill-cli [--json] [--base-dir DIR] skill regenerate --slug author-slug
```
- 从 `writing.md` + `author_persona.md` + `meta.json` 重新生成 `SKILL.md`、`writing_skill.md`、`persona_skill.md`

#### skill delete — 删除 Skill
```bash
author-skill-cli [--json] [--base-dir DIR] skill delete --slug author-slug
```
- 需要二次确认

### 4. evolve — 迭代进化

#### evolve init — 首轮初始化
```bash
author-skill-cli [--json] [--base-dir DIR] evolve init \
  --slug author-slug \
  --novel 小说.txt \
  [--name "作者笔名"] \
  [--count 5]
```
- 采样前 N 章，生成初始分析 Prompt
- 要求 `<base-dir>/<slug>` 目录不存在或为空

#### evolve round — 迭代进化轮次
```bash
author-skill-cli [--json] [--base-dir DIR] evolve round \
  --slug author-slug \
  --novel 小说.txt \
  [--strategy stratified|uncertainty] \
  [--count 5]
```
- `stratified`：分层采样（前/中/后各取）
- `uncertainty`：不确定性采样（优先采样能填补 skill 空白的章节）
- 自动排除已采样章节

### 5. validate — 收敛验证

#### validate run — 执行验证
```bash
author-skill-cli [--json] [--base-dir DIR] validate run \
  --slug author-slug \
  --novel 小说.txt
```
- 生成验证 Prompt（骨架大纲提取 + Skill AI 写作 + 多维评分）

#### validate parse-score — 解析 LLM 评分
```bash
author-skill-cli [--json] validate parse-score [--text "评分文本"]
```
- 也可通过 stdin 传入评分文本
- 解析维度：叙事声音、节奏韵律、对话风格、描写偏好、用词习惯

#### validate record — 记录评分
```bash
author-skill-cli [--json] [--base-dir DIR] validate record \
  --slug author-slug \
  --score 7.5 \
  [--dimension-scores '{"叙事声音":7.0,"节奏韵律":8.0}']
```

#### validate check — 判定收敛
```bash
author-skill-cli [--json] [--base-dir DIR] validate check \
  --slug author-slug \
  [--threshold 0.3]
```
- 连续 2 轮提升 < 阈值 → 判定收敛
- 检测过拟合（近期评分下降）

### 6. version — 版本管理

#### version list — 列出版本
```bash
author-skill-cli [--json] [--base-dir DIR] version list --slug author-slug
```

#### version backup — 备份当前版本
```bash
author-skill-cli [--json] [--base-dir DIR] version backup --slug author-slug
```

#### version rollback — 回滚到指定版本
```bash
author-skill-cli [--json] [--base-dir DIR] version rollback --slug author-slug --version v1
```
- 原子性操作：先备份当前版本，再恢复目标版本
- 自动清理超出限制的旧版本

#### version cleanup — 清理旧版本
```bash
author-skill-cli [--json] [--base-dir DIR] version cleanup --slug author-slug [--max-versions 10]
```

### 7. sample — 章节采样
```bash
author-skill-cli [--json] sample \
  --novel 小说.txt \
  --strategy initial|stratified|uncertainty \
  [--count 5] \
  [--exclude 0,3,7] \
  [--skill-file skill.md]
```
- `initial`：取前 N 章
- `stratified`：分层采样
- `uncertainty`：不确定性采样（需要 `--skill-file`）

## 典型工作流程

### 完整蒸馏流程
```bash
# 1. 准备：收集原材料 + 生成分析 Prompt
author-skill-cli --base-dir ./authors distill prepare \
  --name "烽火戏诸侯" --novels 雪中悍刀行.txt --comments 评论.txt --platform 起点

# 2. 用户将 Prompt 发给 LLM，LLM 返回 writing.md 和 author_persona.md

# 3. 创建 Skill
author-skill-cli --base-dir ./authors distill create \
  --slug feng-huo-xi-zhu-hou --name "烽火戏诸侯" \
  --writing writing.md --persona author_persona.md

# 4. 迭代进化
author-skill-cli --base-dir ./authors evolve round \
  --slug feng-huo-xi-zhu-hou --novel 雪中悍刀行.txt --strategy stratified

# 5. 收敛验证
author-skill-cli --base-dir ./authors validate run \
  --slug feng-huo-xi-zhu-hou --novel 雪中悍刀行.txt
```

### 对话纠正流程
```bash
# 发现 Skill 输出不符合预期时
author-skill-cli --base-dir ./authors skill correct \
  --slug feng-huo-xi-zhu-hou \
  --wrong "用被动语态描写战斗" \
  --correct "用短句主动语态营造紧迫感" \
  --scene "战斗描写"
```

### 版本回滚流程
```bash
# 查看历史版本
author-skill-cli --base-dir ./authors version list --slug feng-huo-xi-zhu-hou

# 回滚到 v3
author-skill-cli --base-dir ./authors version rollback --slug feng-huo-xi-zhu-hou --version v3
```

## JSON 输出格式

使用 `--json` 时，输出格式统一为：
```json
{
  "success": true,
  "data": { ... },
  "warnings": []
}
```

错误时：
```json
{
  "success": false,
  "error": "错误描述"
}
```

## 注意事项

1. **--base-dir 安全限制**：必须位于当前工作目录或用户目录下，防止路径遍历
2. **slug 命名规则**：仅允许小写字母、数字和连字符（如 `feng-huo-xi-zhu-hou`）
3. **编码处理**：自动尝试 utf-8-sig → utf-8 → gb18030 → gbk 回退
4. **文件大小限制**：txt 小说 100MB、epub 100MB、评论 50MB
5. **版本限制**：默认最多保留 10 个历史版本
6. **Windows 控制台**：JSON 输出中的中文在 GBK 控制台可能显示异常，建议使用 `--json` 配合管道重定向到文件
