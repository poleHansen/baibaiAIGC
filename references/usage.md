# 使用说明

本目录是一套根目录直放式 skill，核心文件如下：

- `SKILL.md`：总控规则，负责定义触发条件、三轮顺序执行、降 AIGC 记录和输出要求。
- `prompts/baibaiAIGC1.md`：第 1 轮改写提示词。
- `prompts/baibaiAIGC2.md`：第 2 轮改写提示词。
- `prompts/baibaiAIGC3.md`：第 3 轮改写提示词。
- `checklist.md`：最终检查与评分规则。

## 执行顺序

多轮降 AIGC 必须严格按以下顺序执行，但每次调用 skill 只执行其中一轮，轮次之间通过“降 AIGC 记录”和中间文件在多个对话中串联：

1. `prompts/baibaiAIGC1.md`
2. `prompts/baibaiAIGC2.md`
3. `prompts/baibaiAIGC3.md`
4. `checklist.md`

上一轮输出必须作为下一轮输入，禁止合并三轮一次性处理，也禁止在单次调用中跨轮混用规则。

## 单轮内部分段规则

即使当前对话只执行一轮，也不能把整篇论文一次性整体降 AIGC。单轮内部必须遵守以下规则：

1. 优先按原始段落切分。
2. 如果某个原始段落超过 850 字，再按完整句子的自然断句位置继续切分。
3. 每个处理块最多 850 字。
4. 不允许在句子中间、术语中间、编号中间随意截断。
5. 逐块处理完成后，必须按原段落结构还原，最终保持原段落顺序和基本空行结构。

当用户是在聊天框中直接触发降 AIGC skill 时，默认且必须优先使用对话 skill 模式完成当前轮处理，不应先切换到脚本 API 模式。

如果是在聊天框中按 skill 模式执行，推荐复用 `scripts/skill_round_helper.py`：它负责判断当前轮次、准备 `.txt/.docx` 输入、生成本轮中间文件路径，并在改写完成后继续通过共享 round service 落盘和更新记录。

`scripts/run_aigc_round.py` 仅用于用户明确要求命令行、批处理或脚本 API 自动调用模型的场景，不应作为聊天模式下的默认方案。

## 两种使用方式

当前仓库同时支持两种入口，但聊天触发时必须默认走对话 skill 模式：

1. 对话 skill 模式：直接在聊天框中触发降 AIGC skill，由对话按 `SKILL.md` 的规则执行单轮分段改写。这种方式不需要你自己配置模型 API，也是聊天场景下的默认且强制优先入口。
2. 脚本 API 模式：使用 `scripts/run_aigc_round.py` 执行单轮分段处理；只有在用户明确要求脚本/API/命令行批处理时才应进入该模式。提供 OpenAI 兼容模型 API 配置后，脚本会逐块调用模型自动改写；如果不提供 API 配置，脚本默认直接报错，只有显式使用 `--dry-run` 时才只执行切块与还原校验。

请明确区分这两种模式：

1. 如果是在聊天对话中直接调用本 skill 做当前轮改写，不应要求用户提供 `BAIBAIAIGC_API_KEY`、`BAIBAIAIGC_MODEL`、`BAIBAIAIGC_BASE_URL`。
2. 只有当明确要运行 `scripts/run_aigc_round.py`，并让脚本自动调用外部 OpenAI 兼容接口时，才需要提供上述环境变量或对应命令行参数。
3. 如果脚本模式下没有提供 API 配置，正确的理解应是“脚本不会自动改写”；此时要么补齐 `api_key + model + base_url`，要么显式加 `--dry-run` 仅做切块与 prompt 输入校验，而不是把它理解成“对话 skill 模式也无法使用”。
4. 如果用户是在聊天框里直接说“降 AIGC”“降 ai”“去 AI 味”，应默认优先走对话 skill 模式；除非用户明确要求跑脚本，否则不要主动切到 `scripts/run_aigc_round.py`。
5. 即使脚本 API 变量缺失、为空，或者用户跳过提供，也不应停止任务；应立即回退到对话 skill 路径，继续完成当前轮改写，而不是反复索取同一组变量。
6. 如果用户没有明确要求脚本方案，则不应主动输出 PowerShell、bat、Python 脚本、环境变量设置命令或 API 调用示例。

## 推荐调用示例

### 示例 1：在当前对话执行一轮

```text
请使用当前目录下的降 AIGC skill，对下面这段论文文本执行当前应执行的降 AIGC 轮次（自动根据降 AIGC 记录判断是第 1 轮、第 2 轮还是第 3 轮），完成本轮改写后按 checklist.md 快速评分，并在回复结尾提示我：如需继续下一轮降重，需要新开一个聊天窗口再调用本 skill。
```

### 示例 2：从第 1 轮开始完整走完三轮（需要多次对话）

```text
这是第一次对这篇论文做降 AIGC，请使用当前 skill 从第 1 轮开始，对下面文本执行一轮降重，并记录本轮使用的 prompt 和输出文件路径。完成后请提醒我：如果要继续第 2 轮，需要新开一个聊天窗口再次调用本 skill。
```

### 示例 2.1：通过脚本执行单轮分段处理

```powershell
python scripts/run_aigc_round.py origin/毕业论文_原始_utf8.txt 1 origin/毕业论文_原始_utf8.txt finish/intermediate/毕业论文_原始_utf8_round1.txt finish/intermediate/毕业论文_原始_utf8_round1_manifest.json --chunk-limit 850
```

这个命令需要已经配置模型 API，脚本会先切块，再逐块处理，最后按原段落结构还原，并同步更新 `finish/aigc_records.json`。

### 示例 2.2：通过脚本直连模型 API

```powershell
$env:BAIBAIAIGC_API_KEY="your_api_key"
$env:BAIBAIAIGC_MODEL="your_model"
$env:BAIBAIAIGC_BASE_URL="https://your-endpoint/v1"
python scripts/run_aigc_round.py origin/毕业论文_原始_utf8.txt 1 origin/毕业论文_原始_utf8.txt finish/intermediate/毕业论文_原始_utf8_round1.txt finish/intermediate/毕业论文_原始_utf8_round1_manifest.json --chunk-limit 850
```

也可以显式传参：

```powershell
python scripts/run_aigc_round.py origin/毕业论文_原始_utf8.txt 1 origin/毕业论文_原始_utf8.txt finish/intermediate/毕业论文_原始_utf8_round1.txt finish/intermediate/毕业论文_原始_utf8_round1_manifest.json --chunk-limit 850 --api-key your_api_key --model your_model --base-url https://your-endpoint/v1
```

脚本 API 模式使用的是 OpenAI 兼容 `chat/completions` 接口。

### 示例 2.3：仅校验切块与 prompt 输入

```powershell
python scripts/run_aigc_round.py origin/毕业论文_原始_utf8.txt 1 origin/毕业论文_原始_utf8.txt finish/intermediate/毕业论文_原始_utf8_round1.txt finish/intermediate/毕业论文_原始_utf8_round1_manifest.json --chunk-limit 850 --dry-run --echo-prompt-inputs
```

这个命令不会调用模型，输出文本会与输入文本一致，只用于检查切块结构和每块 prompt 输入是否符合预期。

### 示例 3：显式要求展示中间轮次（多次对话完成）

```text
这篇论文我希望完整走完三轮降 AIGC。请在当前对话中只执行当前应执行的一轮（根据降 AIGC 记录判断是第 1、2 还是 3 轮），展示本轮结果和评分，并说明本轮是第几轮。完成后提醒我新开聊天窗口继续下一轮。
```

## 使用约束

- 不新增数据、文献、案例、结论。
- 不破坏原文术语、编号和段落结构。
- 单轮内部必须分段处理，不能整篇一次性改写。
- 如果原文已经较自然，应最小化修改。
- 默认保持论文语体，不改成营销文案或过度口语化表达。
