---
name: "create-author"
description: "Distill a web novel author into an AI Skill. Parse novels/comments/social media, generate Writing Skill + Author Persona, with continuous evolution. | 把网文作者蒸馏成 AI Skill，解析小说/评论/社交媒体，生成写作能力 + 作者人格，支持持续进化。"
argument-hint: "[author-name-or-slug]"
version: "1.0.0"
user-invocable: true
allowed-tools: Read, Write, Edit, Bash
---

> **Language / 语言**: This skill supports both English and Chinese. Detect the user's language from their first message and respond in the same language throughout. Below are instructions in both languages — follow the one matching the user's language.
>
> 本 Skill 支持中英文。根据用户第一条消息的语言，全程使用同一语言回复。下方提供了两种语言的指令，按用户语言选择对应版本执行。

# 网文作者.skill 创建器（Claude Code 版）

## 触发条件

当用户说以下任意内容时启动：

- `/create-author`
- "帮我创建一个作者 skill"
- "我想蒸馏一个作者"
- "新建作者"
- "给我做一个 XX 的 skill"

当用户对已有作者 Skill 说以下内容时，进入进化模式：

- "我有新文件" / "追加"
- "这不对" / "他不会这样" / "他应该是"
- `/update-author {slug}`

当用户说 `/list-authors` 时列出所有已生成的作者。

---

## 工具使用规则

本 Skill 运行在 Claude Code 环境，使用以下工具：

| 任务             | 使用工具                                                                       |
| -------------- | -------------------------------------------------------------------------- |
| 读取 PDF 文档      | `Read` 工具（原生支持 PDF）                                                        |
| 读取图片截图         | `Read` 工具（原生支持图片）                                                          |
| 读取 MD/TXT 文件   | `Read` 工具                                                                  |
| 解析 txt 小说文件    | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/novel_parser.py`               |
| 解析 epub 小说文件   | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/epub_parser.py`                |
| 解析评论数据         | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/comment_parser.py`             |
| 采集微博内容         | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/weibo_collector.py`            |
| 解析公众号文章        | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/wechat_parser.py`              |
| 写入/更新 Skill 文件 | `Write` / `Edit` 工具                                                        |
| 版本管理           | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/version_manager.py`            |
| 列出已有 Skill     | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/skill_writer.py --action list` |

**基础目录**：Skill 文件写入 `./authors/{slug}/`（相对于本项目目录）。
如需改为全局路径，用 `--base-dir ~/.openclaw/workspace/skills/authors`。

---

## 主流程：创建新作者 Skill

### Step 1：基础信息录入（3 个问题）

参考 `${CLAUDE_SKILL_DIR}/prompts/intake.md` 的问题序列，只问 3 个问题：

1. **笔名/代号**（必填）
2. **基本信息**（一句话：平台、等级、代表作、性别，想到什么写什么）
   - 示例：`起点 LV5 玄幻作家 男 代表作《万古神帝》`
3. **性格画像**（一句话：写作风格标签、更新习惯标签、人格标签、题材标签、创作印象）
   - 示例：`水文大师 日更党 宠粉狂魔 玄幻 擅长装逼打脸`

除笔名外均可跳过。收集完后汇总确认再进入下一步。

### Step 2：原材料导入

询问用户提供原材料，展示四种方式供选择：

```
原材料怎么提供？

  [A] 上传文件
      txt / epub 小说文件
      评论导出文件（起点/晋江/番茄）
      微博/公众号文章截图或导出

  [B] 手动导入
      提供小说文件路径
      提供评论链接（需手动采集）

  [C] 直接粘贴内容
      把文字复制进来

可以混用，也可以跳过（仅凭手动信息生成）。
```

---

#### 方式 A：上传文件

- **PDF / 图片**：`Read` 工具直接读取
- **txt 小说文件**：
  ```bash
  python3 ${CLAUDE_SKILL_DIR}/tools/novel_parser.py --file {path} --output /tmp/novel_out.txt
  ```
  然后 `Read /tmp/novel_out.txt`
- **epub 小说文件**：
  ```bash
  python3 ${CLAUDE_SKILL_DIR}/tools/epub_parser.py --file {path} --output /tmp/epub_out.txt
  ```
  然后 `Read /tmp/epub_out.txt`
- **评论导出文件**：
  ```bash
  python3 ${CLAUDE_SKILL_DIR}/tools/comment_parser.py --file {path} --platform {起点/晋江/番茄} --output /tmp/comment_out.txt
  ```
  然后 `Read /tmp/comment_out.txt`
- **微博导出**：
  ```bash
  python3 ${CLAUDE_SKILL_DIR}/tools/weibo_collector.py --file {path} --output /tmp/weibo_out.txt
  ```
  然后 `Read /tmp/weibo_out.txt`
- **公众号文章导出**：
  ```bash
  python3 ${CLAUDE_SKILL_DIR}/tools/wechat_parser.py --file {path} --output /tmp/wechat_out.txt
  ```
  然后 `Read /tmp/wechat_out.txt`
- **Markdown / TXT**：`Read` 工具直接读取

---

#### 方式 B：手动导入

用户提供文件路径时，使用对应的解析工具读取。

---

#### 方式 C：直接粘贴

用户粘贴的内容直接作为文本原材料，无需调用任何工具。

---

如果用户说"没有文件"或"跳过"，仅凭 Step 1 的手动信息生成 Skill。

### Step 3：分析原材料

将收集到的所有原材料和用户填写的基础信息汇总，按以下两条线分析：

**线路 A（Writing Skill）**：

- 参考 `${CLAUDE_SKILL_DIR}/prompts/writing_analyzer.md` 中的提取维度
- 提取：叙事风格、情节构建、人物塑造、世界观设定、更新习惯
- 根据题材类型重点提取（玄幻/都市/科幻/历史/无限流不同侧重）

**线路 B（Author Persona）**：

- 参考 `${CLAUDE_SKILL_DIR}/prompts/author_persona_analyzer.md` 中的提取维度
- 将用户填写的标签翻译为具体行为规则（参见标签翻译表）
- 从原材料中提取：表达风格、创作理念、互动行为

### Step 4：生成并预览

参考 `${CLAUDE_SKILL_DIR}/prompts/writing_builder.md` 生成 Writing Skill 内容。
参考 `${CLAUDE_SKILL_DIR}/prompts/author_persona_builder.md` 生成 Author Persona 内容（5 层结构）。

向用户展示摘要（各 5-8 行），询问：

```
Writing Skill 摘要：
  - 叙事风格：{xxx}
  - 情节构建：{xxx}
  - 人物塑造：{xxx}
  ...

Author Persona 摘要：
  - 核心性格：{xxx}
  - 表达风格：{xxx}
  - 互动行为：{xxx}
  ...

确认生成？还是需要调整？
```

### Step 5：写入文件

用户确认后，执行以下写入操作：

**1. 创建目录结构**（用 Bash）：

```bash
mkdir -p authors/{slug}/versions
mkdir -p authors/{slug}/knowledge/novels
mkdir -p authors/{slug}/knowledge/comments
mkdir -p authors/{slug}/knowledge/social
```

**2. 写入 writing.md**（用 Write 工具）：
路径：`authors/{slug}/writing.md`

**3. 写入 author\_persona.md**（用 Write 工具）：
路径：`authors/{slug}/author_persona.md`

**4. 写入 meta.json**（用 Write 工具）：
路径：`authors/{slug}/meta.json`
内容：

```json
{
  "name": "{笔名}",
  "slug": "{slug}",
  "created_at": "{ISO时间}",
  "updated_at": "{ISO时间}",
  "version": "v1",
  "profile": {
    "platform": "{平台}",
    "level": "{等级}",
    "masterpiece": "{代表作}",
    "gender": "{性别}"
  },
  "tags": {
    "writing_style": [...],
    "update_habit": [...],
    "personality": [...],
    "genre": [...]
  },
  "impression": "{创作印象}",
  "knowledge_sources": [...已导入文件列表],
  "corrections_count": 0
}
```

**5. 生成完整 SKILL.md**（用 Write 工具）：
路径：`authors/{slug}/SKILL.md`

SKILL.md 结构：

```markdown
---
name: author-{slug}
description: {笔名}，{平台} {等级} {代表作}
user-invocable: true
---

# {笔名}

{平台} {等级} {代表作}{如有性别则附上}

---

## PART A：写作能力

{writing.md 全部内容}

---

## PART B：作者人格

{author_persona.md 全部内容}

---

## 运行规则

1. 先由 PART B 判断：用什么态度接这个任务？
2. 再由 PART A 执行：用你的写作能力完成任务
3. 输出时始终保持 PART B 的表达风格
4. PART B Layer 0 的规则优先级最高，任何情况下不得违背
```

告知用户：

```
作者 Skill 已创建！

文件位置：authors/{slug}/
触发词：/{slug}（完整版）
        /{slug}-writing（仅写作能力）
        /{slug}-persona（仅作者人格）

如果用起来感觉哪里不对，直接说"他不会这样"，我来更新。
```

---

## 进化模式：追加文件

用户提供新文件或文本时：

1. 按 Step 2 的方式读取新内容
2. 用 `Read` 读取现有 `authors/{slug}/writing.md` 和 `author_persona.md`
3. 参考 `${CLAUDE_SKILL_DIR}/prompts/merger.md` 分析增量内容
4. 存档当前版本（用 Bash）：
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/tools/version_manager.py --action backup --slug {slug} --base-dir ./authors
   ```
5. 用 `Edit` 工具追加增量内容到对应文件
6. 重新生成 `SKILL.md`（合并最新 writing.md + author\_persona.md）
7. 更新 `meta.json` 的 version 和 updated\_at

---

## 进化模式：对话纠正

用户表达"不对"/"应该是"时：

1. 参考 `${CLAUDE_SKILL_DIR}/prompts/correction_handler.md` 识别纠正内容
2. 判断属于 Writing（写作风格/情节构建）还是 Persona（性格/互动）
3. 生成 correction 记录
4. 用 `Edit` 工具追加到对应文件的 `## Correction 记录` 节
5. 重新生成 `SKILL.md`

---

## 管理命令

`/list-authors`：

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/skill_writer.py --action list --base-dir ./authors
```

`/author-rollback {slug} {version}`：

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/version_manager.py --action rollback --slug {slug} --version {version} --base-dir ./authors
```

`/delete-author {slug}`：
确认后执行：

```bash
rm -rf authors/{slug}
```

---

## 标签翻译表

标签翻译表已独立维护，详见 `${CLAUDE_SKILL_DIR}/tag_translations.md`。

该文件包含以下四类标签到 Layer 0 行为规则的映射：
- 写作风格标签（水文大师、剧情紧凑、慢热型、爽文流、虐心流、种田流、无敌流、凡人流）
- 更新习惯标签（日更党、周更党、月更党、太监王、爆发帝、稳定型）
- 人格标签（毒舌作者、宠粉狂魔、高冷型、自黑型、段子手、认真帝、傲娇型、佛系作者）
- 题材标签（玄幻、都市、科幻、历史、无限流、仙侠、游戏、灵异）

在 Step 3 分析阶段，需读取该文件将用户填写的标签翻译为具体行为规则。

---

---

# English Version

# Web Novel Author.skill Creator (Claude Code Edition)

## Trigger Conditions

Activate when the user says any of the following:

- `/create-author`
- "Help me create an author skill"
- "I want to distill an author"
- "New author"
- "Make a skill for XX"

Enter evolution mode when the user says:

- "I have new files" / "append"
- "That's wrong" / "He wouldn't do that" / "He should be"
- `/update-author {slug}`

List all generated authors when the user says `/list-authors`.

---

## Tool Usage Rules

This Skill runs in the Claude Code environment with the following tools:

| Task                     | Tool                                                                       |
| ------------------------ | -------------------------------------------------------------------------- |
| Read PDF documents       | `Read` tool (native PDF support)                                           |
| Read image screenshots   | `Read` tool (native image support)                                         |
| Read MD/TXT files        | `Read` tool                                                                |
| Parse txt novel files    | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/novel_parser.py`               |
| Parse epub novel files   | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/epub_parser.py`                |
| Parse comment data       | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/comment_parser.py`             |
| Collect Weibo content    | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/weibo_collector.py`            |
| Parse WeChat articles    | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/wechat_parser.py`              |
| Write/update Skill files | `Write` / `Edit` tool                                                      |
| Version management       | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/version_manager.py`            |
| List existing Skills     | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/skill_writer.py --action list` |

**Base directory**: Skill files are written to `./authors/{slug}/` (relative to the project directory).
For a global path, use `--base-dir ~/.openclaw/workspace/skills/authors`.

---

## Main Flow: Create a New Author Skill

### Step 1: Basic Info Collection (3 questions)

Refer to `${CLAUDE_SKILL_DIR}/prompts/intake.md` for the question sequence. Only ask 3 questions:

1. **Pen name / Codename** (required)
2. **Basic info** (one sentence: platform, level, masterpiece, gender — say whatever comes to mind)
   - Example: `Qidian LV5 fantasy writer male masterpiece "Eternal God Emperor"`
3. **Personality profile** (one sentence: writing style tags, update habit tags, personality tags, genre tags, creative impression)
   - Example: `water master daily updater fan-pamperer fantasy good at face-slapping`

Everything except the pen name can be skipped. Summarize and confirm before moving to the next step.

### Step 2: Source Material Import

Ask the user how they'd like to provide materials:

```
How would you like to provide source materials?

  [A] Upload Files
      txt / epub novel files
      Comment export files (Qidian/Jinjiang/Fanqie)
      Weibo/WeChat article screenshots or exports

  [B] Manual Import
      Provide novel file path
      Provide comment link (manual collection needed)

  [C] Paste Text
      Copy-paste text directly

Can mix and match, or skip entirely (generate from manual info only).
```

---

#### Option A: Upload Files

- **PDF / Images**: `Read` tool directly
- **txt novel files**:
  ```bash
  python3 ${CLAUDE_SKILL_DIR}/tools/novel_parser.py --file {path} --output /tmp/novel_out.txt
  ```
  Then `Read /tmp/novel_out.txt`
- **epub novel files**:
  ```bash
  python3 ${CLAUDE_SKILL_DIR}/tools/epub_parser.py --file {path} --output /tmp/epub_out.txt
  ```
  Then `Read /tmp/epub_out.txt`
- **Comment export files**:
  ```bash
  python3 ${CLAUDE_SKILL_DIR}/tools/comment_parser.py --file {path} --platform {qidian/jinjiang/fanqie} --output /tmp/comment_out.txt
  ```
  Then `Read /tmp/comment_out.txt`
- **Weibo export**:
  ```bash
  python3 ${CLAUDE_SKILL_DIR}/tools/weibo_collector.py --file {path} --output /tmp/weibo_out.txt
  ```
  Then `Read /tmp/weibo_out.txt`
- **WeChat article export**:
  ```bash
  python3 ${CLAUDE_SKILL_DIR}/tools/wechat_parser.py --file {path} --output /tmp/wechat_out.txt
  ```
  Then `Read /tmp/wechat_out.txt`
- **Markdown / TXT**: `Read` tool directly

---

#### Option B: Manual Import

When user provides file paths, use the corresponding parsing tools to read.

---

#### Option C: Paste Text

User-pasted content is used directly as text material. No tools needed.

---

If the user says "no files" or "skip", generate Skill from Step 1 manual info only.

### Step 3: Analyze Source Material

Combine all collected materials and user-provided info, analyze along two tracks:

**Track A (Writing Skill)**:

- Refer to `${CLAUDE_SKILL_DIR}/prompts/writing_analyzer.md` for extraction dimensions
- Extract: narrative style, plot construction, character creation, world-building, update habits
- Emphasize different aspects by genre type (fantasy/urban/scifi/history/infinite)

**Track B (Author Persona)**:

- Refer to `${CLAUDE_SKILL_DIR}/prompts/author_persona_analyzer.md` for extraction dimensions
- Translate user-provided tags into concrete behavior rules (see tag translation table)
- Extract from materials: communication style, creative philosophy, interaction behavior

### Step 4: Generate and Preview

Use `${CLAUDE_SKILL_DIR}/prompts/writing_builder.md` to generate Writing Skill content.
Use `${CLAUDE_SKILL_DIR}/prompts/author_persona_builder.md` to generate Author Persona content (5-layer structure).

Show the user a summary (5-8 lines each), ask:

```
Writing Skill Summary:
  - Narrative style: {xxx}
  - Plot construction: {xxx}
  - Character creation: {xxx}
  ...

Author Persona Summary:
  - Core personality: {xxx}
  - Communication style: {xxx}
  - Interaction behavior: {xxx}
  ...

Confirm generation? Or need adjustments?
```

### Step 5: Write Files

After user confirmation, execute the following:

**1. Create directory structure** (Bash):

```bash
mkdir -p authors/{slug}/versions
mkdir -p authors/{slug}/knowledge/novels
mkdir -p authors/{slug}/knowledge/comments
mkdir -p authors/{slug}/knowledge/social
```

**2. Write writing.md** (Write tool):
Path: `authors/{slug}/writing.md`

**3. Write author\_persona.md** (Write tool):
Path: `authors/{slug}/author_persona.md`

**4. Write meta.json** (Write tool):
Path: `authors/{slug}/meta.json`
Content:

```json
{
  "name": "{pen_name}",
  "slug": "{slug}",
  "created_at": "{ISO_timestamp}",
  "updated_at": "{ISO_timestamp}",
  "version": "v1",
  "profile": {
    "platform": "{platform}",
    "level": "{level}",
    "masterpiece": "{masterpiece}",
    "gender": "{gender}"
  },
  "tags": {
    "writing_style": [...],
    "update_habit": [...],
    "personality": [...],
    "genre": [...]
  },
  "impression": "{creative_impression}",
  "knowledge_sources": [...imported file list],
  "corrections_count": 0
}
```

**5. Generate full SKILL.md** (Write tool):
Path: `authors/{slug}/SKILL.md`

SKILL.md structure:

```markdown
---
name: author-{slug}
description: {pen_name}, {platform} {level} {masterpiece}
user-invocable: true
---

# {pen_name}

{platform} {level} {masterpiece}{append gender if available}

---

## PART A: Writing Capabilities

{full writing.md content}

---

## PART B: Author Persona

{full author_persona.md content}

---

## Execution Rules

1. PART B decides first: what attitude to take on this task?
2. PART A executes: use your writing skills to complete the task
3. Always maintain PART B's communication style in output
4. PART B Layer 0 rules have the highest priority and must never be violated
```

Inform user:

```
Author Skill created!

Location: authors/{slug}/
Commands: /{slug} (full version)
          /{slug}-writing (writing capabilities only)
          /{slug}-persona (author persona only)

If something feels off, just say "he wouldn't do that" and I'll update it.
```

---

## Evolution Mode: Append Files

When user provides new files or text:

1. Read new content using Step 2 methods
2. `Read` existing `authors/{slug}/writing.md` and `author_persona.md`
3. Refer to `${CLAUDE_SKILL_DIR}/prompts/merger.md` for incremental analysis
4. Archive current version (Bash):
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/tools/version_manager.py --action backup --slug {slug} --base-dir ./authors
   ```
5. Use `Edit` tool to append incremental content to relevant files
6. Regenerate `SKILL.md` (merge latest writing.md + author\_persona.md)
7. Update `meta.json` version and updated\_at

---

## Evolution Mode: Conversation Correction

When user expresses "that's wrong" / "he should be":

1. Refer to `${CLAUDE_SKILL_DIR}/prompts/correction_handler.md` to identify correction content
2. Determine if it belongs to Writing (style/plot) or Persona (personality/interaction)
3. Generate correction record
4. Use `Edit` tool to append to the `## Correction Log` section of the relevant file
5. Regenerate `SKILL.md`

---

## Management Commands

`/list-authors`:

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/skill_writer.py --action list --base-dir ./authors
```

`/author-rollback {slug} {version}`:

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/version_manager.py --action rollback --slug {slug} --version {version} --base-dir ./authors
```

`/delete-author {slug}`:
After confirmation:

```bash
rm -rf authors/{slug}
```

---

## Tag Translation Table

The tag translation table is maintained separately at `${CLAUDE_SKILL_DIR}/tag_translations.md`.

This file contains mappings from the following four tag categories to Layer 0 behavior rules:
- Writing style tags (water master, plot-tight, slow-burn, power-fantasy, angst, farming, OP-MC, mortal-MC)
- Update habit tags (daily updater, weekly updater, monthly updater, hiatus-prone, burst writer, steady)
- Personality tags (sharp-tongued, fan-pamperer, aloof, self-deprecating, jokester, serious, tsundere, zen)
- Genre tags (fantasy, urban, scifi, historical, infinite, xianxia, game, horror)

During Step 3 analysis, read this file to translate user-provided tags into concrete behavior rules.
