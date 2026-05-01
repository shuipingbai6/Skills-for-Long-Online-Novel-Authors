---
name: "create-author"
description: "把网文作者蒸馏成 AI Skill，解析小说/评论/社交媒体，生成写作能力 + 作者人格，支持迭代进化。"
argument-hint: "[author-name-or-slug]"
version: "1.0.0"
user-invocable: true
allowed-tools: Read, Write, Edit, Bash
---

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
- `/evolve-author {slug}`（迭代进化）
- `/validate-author {slug}`（收敛验证）

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
| 智能章节采样       | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/chapter_sampler.py`            |
| 迭代蒸馏编排       | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/iterative_distill.py`          |
| 收敛验证           | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/convergence_checker.py`        |
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
  "corrections_count": 0,
  "evolution": {
    "total_rounds": 0,
    "chapters_sampled": [],
    "rounds": [],
    "convergence": {
      "is_converged": false,
      "last_validation_scores": null,
      "consecutive_small_gains": 0
    }
  }
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

## 进化模式：迭代进化

当用户说 `/evolve-author {slug}` 或"进化"时，进入迭代进化模式：

### Round 0：初始化（如该作者尚无 Skill）

1. 询问用户提供小说文件
2. 使用 `Bash` 采样前 5~10 章：
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/tools/chapter_sampler.py --novel {path} --strategy initial --count 5
   ```
3. 按 Step 3-5 的流程生成初始 Skill（skill v1）
4. 在 meta.json 中初始化 `evolution` 字段

### Round N：迭代进化（如该作者已有 Skill）

1. **恢复进化状态**：用 `Read` 读取 `authors/{slug}/meta.json`，获取以下关键信息：
   - `evolution.total_rounds`：当前已进化轮次（决定下一轮是 Round N+1）
   - `evolution.chapters_sampled`：已采样章节索引列表（用于 --exclude 参数，避免重复采样）
   - `evolution.convergence`：收敛状态（如果已收敛，提示用户无需继续进化）
   - `knowledge_sources`：小说文件路径（如果用户未提供小说路径，使用此路径）

   向用户展示当前状态：
   ```
   当前进化状态：
   - 版本：v{N}
   - 已进化轮次：{total_rounds}
   - 已采样章节：{chapters_sampled 列表}
   - 收敛状态：{已收敛/未收敛}
   ```

2. **采样策略选择**：
   - 前 2-3 轮：分层采样（stratified）
   - 第 3 轮起：不确定性采样（uncertainty）

3. **采样新章节**（5 章）：
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/tools/chapter_sampler.py --novel {path} --strategy {stratified/uncertainty} --count 5 --exclude {meta.json中chapters_sampled的值，逗号分隔} --skill-file {skill_dir}/writing.md
   ```

4. **读取当前 Skill**：用 `Read` 读取 `authors/{slug}/writing.md` 和 `author_persona.md`

5. **重整 Skill**：
   - 参考 `${CLAUDE_SKILL_DIR}/prompts/merger.md`（重整式更新策略）
   - 将新章节观察融入已有 Skill，输出重写后的完整 writing.md 和 author_persona.md
   - **关键：每轮重写，而非追加**

6. **存档当前版本**：
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/tools/version_manager.py --action backup --slug {slug} --base-dir ./authors
   ```

7. **写入新 Skill**：用 `Write` 工具重写 writing.md 和 author_persona.md

8. **重新生成 SKILL.md**（合并最新 writing.md + author_persona.md）

9. **更新 meta.json**：
   - version: v(N+1)
   - evolution.total_rounds: +1
   - evolution.chapters_sampled: 追加本轮采样索引
   - evolution.rounds: 追加本轮记录

10. **展示本轮更新摘要**，等待用户确认是否继续

### 收敛验证

当用户说 `/validate-author {slug}` 或"验证"时：

1. **恢复进化状态**：用 `Read` 读取 `authors/{slug}/meta.json`，确认当前版本和已采样章节

2. **采样验证章节**（3 章，前/中/后各 1 章）：
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/tools/convergence_checker.py --action validate --slug {slug} --novel {path} --base-dir ./authors
   ```

2. **生成骨架大纲**：参考 `${CLAUDE_SKILL_DIR}/prompts/skeleton_outline.md`，从原文提取事件骨架

3. **Skill AI 按大纲写作**：使用当前 Skill 的 AI，根据骨架大纲写一章（**必须用与创建 Skill 不同的 AI**）

4. **对比 AI 多维评分**：将生成文本与原文发送给另一个 AI，按 5 维评分表评分（**必须用与 Skill AI 不同的 AI**）
   - 参考 `${CLAUDE_SKILL_DIR}/prompts/style_validator.md`

5. **记录评分并判定收敛**：
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/tools/convergence_checker.py --action record --slug {slug} --score {综合分} --dimension-scores '{JSON}' --base-dir ./authors
   python3 ${CLAUDE_SKILL_DIR}/tools/convergence_checker.py --action check --slug {slug} --base-dir ./authors
   ```

6. **收敛判据**：连续 2 轮迭代，5 维综合评分的提升幅度均 < 0.3，则判定为收敛

7. **详细指南**：参考 `${CLAUDE_SKILL_DIR}/docs/evolution_guide.md`

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
