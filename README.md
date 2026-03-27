# baibaiAIGC

一个用于中文论文、摘要、课程作业和技术文档多轮降 AIGC 改写的工作目录。

本仓库支持两种使用方式：

1. 对话 skill 模式：在聊天中按 `SKILL.md` 约束执行单轮改写。
2. 脚本 API 模式：通过 `scripts/run_aigc_round.py` 执行单轮分段处理，并按需调用外部 OpenAI 兼容接口。

核心原则：

- 三轮顺序固定为 `1 -> 2 -> 3`，不能跳轮，不能合并执行。
- 每次调用只处理一轮。
- 单轮内部也必须先分块，再逐块改写，最后按原段落结构还原。
- 不新增事实、数据、文献、案例或结论。
- 保留原文术语、编号、逻辑关系和论文语体。

## 适用场景

适合以下任务：

- 中文论文去 AI 味
- 多轮降低 AIGC 痕迹
- 对长文档进行分段改写并保留原有结构
- 基于 `.docx` 和 `.txt` 的论文处理工作流

不适合以下任务：

- 一次性把三轮规则混合执行
- 把整篇长文一次性整体重写
- 为了“过检测”而随意改动事实或专业内容

## 目录结构

```text
.
├─ SKILL.md
├─ README.md
├─ requirements.txt
├─ origin/
├─ finish/
│  └─ intermediate/
├─ prompts/
│  ├─ baibaiAIGC1.md
│  ├─ baibaiAIGC2.md
│  └─ baibaiAIGC3.md
├─ references/
│  ├─ checklist.md
│  └─ usage.md
└─ scripts/
   ├─ aigc_records.py
   ├─ aigc_round_service.py
   ├─ chunking.py
   ├─ docx_pipeline.py
   ├─ llm_client.py
   ├─ run_aigc_round.py
   └─ skill_round_helper.py
```

目录约定：

- `origin/`：放原始输入文件，通常是 `.txt` 或 `.docx`。
- `finish/intermediate/`：放每一轮的中间文本、提取文本和 manifest。
- `finish/`：放最终产物，以及 `aigc_records.json` 这类记录文件。
- `prompts/`：三轮提示词，严格按顺序使用。
- `references/`：使用说明和评分清单。
- `scripts/`：脚本入口和共享处理逻辑。

## 环境要求

- Windows PowerShell 或其他可运行 Python 的终端环境
- Python 3.10+
- 已创建并激活虚拟环境

安装依赖：

```powershell
pip install -r requirements.txt
```

当前依赖非常少：

- `python-docx`：用于 `.docx` 文本提取和回写

## 快速开始

### 1. 准备输入文件

把待处理文件放到 `origin/` 目录。

示例：

- `origin/毕业论文.docx`
- `origin/毕业论文_原始_utf8.txt`

### 2. 选择使用模式

#### 模式 A：对话 skill 模式

适合直接在聊天中执行当前应进行的一轮改写。

特点：

- 不需要你手动配置 `API Key / Model / Base URL`
- 会依据记录判断当前应执行第几轮
- 更适合人工配合审阅的工作流

入口和约束见 [SKILL.md](SKILL.md)。

#### 模式 B：脚本 API 模式

适合用脚本做单轮批处理。

特点：

- 需要提供 OpenAI 兼容接口配置
- 可以自动切块、逐块调用模型、还原结果并写入记录
- 更适合可重复执行的命令行流程

脚本入口是 [scripts/run_aigc_round.py](scripts/run_aigc_round.py)。

## 脚本 API 模式用法

### 必填参数

运行单轮处理：

```powershell
python scripts/run_aigc_round.py <doc_id> <round> <input_path> <output_path> <manifest_path> [--chunk-limit 850]
```

参数说明：

- `doc_id`：文档标识，通常写成 `origin/` 下的相对路径
- `round`：轮次，只能是 `1`、`2`、`3`
- `input_path`：本轮输入文本路径
- `output_path`：本轮输出文本路径
- `manifest_path`：本轮切块结构输出路径

### 配置模型 API

脚本 API 模式需要同时提供以下三项：

- `api_key`
- `model`
- `base_url`

可以通过环境变量提供：

```powershell
$env:BAIBAIAIGC_API_KEY="your_api_key"
$env:BAIBAIAIGC_MODEL="your_model"
$env:BAIBAIAIGC_BASE_URL="https://your-endpoint/v1"
```

也可以通过命令行参数提供：

```powershell
python scripts/run_aigc_round.py origin/毕业论文_原始_utf8.txt 1 origin/毕业论文_原始_utf8.txt finish/intermediate/毕业论文_原始_utf8_round1.txt finish/intermediate/毕业论文_原始_utf8_round1_manifest.json --api-key your_api_key --model your_model --base-url https://your-endpoint/v1
```

### 第 1 轮示例

```powershell
python scripts/run_aigc_round.py origin/毕业论文_原始_utf8.txt 1 origin/毕业论文_原始_utf8.txt finish/intermediate/毕业论文_原始_utf8_round1.txt finish/intermediate/毕业论文_原始_utf8_round1_manifest.json --chunk-limit 850
```

### 第 2 轮示例

```powershell
python scripts/run_aigc_round.py origin/毕业论文_原始_utf8.txt 2 finish/intermediate/毕业论文_原始_utf8_round1.txt finish/intermediate/毕业论文_原始_utf8_round2.txt finish/intermediate/毕业论文_原始_utf8_round2_manifest.json --chunk-limit 850
```

### 第 3 轮示例

```powershell
python scripts/run_aigc_round.py origin/毕业论文_原始_utf8.txt 3 finish/intermediate/毕业论文_原始_utf8_round2.txt finish/intermediate/毕业论文_原始_utf8_round3.txt finish/intermediate/毕业论文_原始_utf8_round3_manifest.json --chunk-limit 850
```

### 仅做切块校验

如果暂时不想调用模型，可以使用 `--dry-run`：

```powershell
python scripts/run_aigc_round.py origin/毕业论文_原始_utf8.txt 1 origin/毕业论文_原始_utf8.txt finish/intermediate/毕业论文_原始_utf8_round1.txt finish/intermediate/毕业论文_原始_utf8_round1_manifest.json --chunk-limit 850 --dry-run --echo-prompt-inputs
```

这个模式下：

- 不会调用模型
- 输出文本与输入文本一致
- 可用于检查切块、prompt 拼接和 manifest 结构

## 对话 skill 模式用法

对话模式建议优先使用 [SKILL.md](SKILL.md) 和 [scripts/skill_round_helper.py](scripts/skill_round_helper.py) 中的规则。

典型流程：

1. 将原始文件放入 `origin/`
2. 在对话中触发降 AIGC skill
3. skill 读取记录，判断当前应执行的轮次
4. 若输入是 `.docx`，先提取为中间 `.txt`
5. 按最多 850 字切块逐块改写
6. 写回本轮输出到 `finish/intermediate/`
7. 依据 `references/checklist.md` 做本轮评分
8. 更新记录，等待下一次新对话继续下一轮

注意：

- 对话 skill 模式不要求额外提供环境变量
- 脚本 API 模式报缺少 API 配置，不等于对话模式不可用

## `.docx` 工作流

如果输入是 `.docx`，推荐使用 [scripts/docx_pipeline.py](scripts/docx_pipeline.py) 做文本提取和回写。

### 从 `.docx` 提取文本

```powershell
python scripts/docx_pipeline.py extract-to-file origin/毕业论文.docx finish/intermediate/毕业论文_extracted.txt
```

### 从 `.docx` 提取段落 JSON

```powershell
python scripts/docx_pipeline.py extract-paragraphs origin/毕业论文.docx finish/intermediate/毕业论文_paragraphs.json
```

### 将文本写回 `.docx`

```powershell
python scripts/docx_pipeline.py build finish/intermediate/毕业论文_原始_utf8_round3.txt finish/毕业论文_终稿.docx
```

### 将段落文件写回 `.docx`

```powershell
python scripts/docx_pipeline.py build-paragraphs finish/intermediate/毕业论文_paragraphs.json finish/毕业论文_终稿.docx
```

## 轮次记录

项目通过 `finish/aigc_records.json` 维护跨对话轮次记录。

记录内容通常包括：

- 原始文档标识
- 已完成轮次
- 每轮使用的 prompt
- 输入输出路径
- chunk 限制和分块数量
- manifest 路径
- 可选评分和时间戳

查看全部记录：

```powershell
python scripts/aigc_records.py show
```

查看单个文档记录：

```powershell
python scripts/aigc_records.py show origin/毕业论文_原始_utf8.txt
```

如果你在自定义集成中需要手动更新记录，可参考 [SKILL.md](SKILL.md) 中定义的数据结构。

## 分段规则

单轮处理必须满足以下规则：

1. 优先按原始段落切分。
2. 若段落超过 850 字，再按完整句子的自然断句继续切分。
3. 不在句子中间、术语中间、编号中间截断。
4. 逐块处理完成后，必须按原段落顺序恢复。

默认单块上限为 `850` 字，可通过 `--chunk-limit` 调整。

## 评分与检查

评分标准见 [references/checklist.md](references/checklist.md)。

建议做两类检查：

1. 每一轮完成后做一次阶段性评分
2. 三轮全部完成后做一次终检评分

重点检查：

- 句式节奏是否过于整齐
- 是否仍存在明显连接词堆积
- 是否有空泛宣传腔、机械排比
- 是否保持论文语体和专业准确性

## 常见问题

### 1. 为什么脚本执行时报缺少 API 配置？

因为 [scripts/run_aigc_round.py](scripts/run_aigc_round.py) 的自动改写依赖外部 OpenAI 兼容接口。

解决方法：

- 配置 `BAIBAIAIGC_API_KEY`
- 配置 `BAIBAIAIGC_MODEL`
- 配置 `BAIBAIAIGC_BASE_URL`

或者使用 `--dry-run` 只做切块校验。

### 2. 为什么对话里能做，脚本里不能做？

因为两者是两种不同入口：

- 对话 skill 模式由对话执行改写逻辑
- 脚本 API 模式由本地脚本调用外部模型接口

它们的依赖边界不同。

### 3. 可以跳过第 1 轮直接做第 2 轮吗？

不建议，也不符合本仓库约束。三轮必须严格顺序执行。

### 4. 可以整篇一次性处理吗？

不可以。长文本必须分段分块处理。

## 推荐工作流

### 工作流 A：人工主导

1. 把 `.docx` 放进 `origin/`
2. 提取为 `.txt`
3. 在聊天中执行第 1 轮
4. 新开对话执行第 2 轮
5. 新开对话执行第 3 轮
6. 终检评分后写回 `.docx`

### 工作流 B：脚本主导

1. 准备 `.txt` 输入
2. 配置 API 环境变量
3. 依次执行第 1、2、3 轮脚本
4. 检查 `finish/intermediate/` 中间结果和 manifest
5. 做最终评分和导出

## 相关文件

- [SKILL.md](SKILL.md)
- [references/usage.md](references/usage.md)
- [references/checklist.md](references/checklist.md)
- [scripts/run_aigc_round.py](scripts/run_aigc_round.py)
- [scripts/skill_round_helper.py](scripts/skill_round_helper.py)
- [scripts/docx_pipeline.py](scripts/docx_pipeline.py)

## 说明

这个 README 面向后续使用者，目的是让使用方式、目录约定和执行边界一次说清。更严格的行为约束以 [SKILL.md](SKILL.md) 为准。