# baibaiAIGC

一个用于中文论文、摘要、课程作业和技术文档多轮降 AIGC 改写的工作目录。

本仓库支持三种使用方式：

1. 对话 skill 模式：在聊天中按 `SKILL.md` 约束执行单轮改写。
2. 脚本 API 模式：通过 `scripts/run_aigc_round.py` 执行单轮分段处理，并按需调用外部 OpenAI 兼容接口。
3. Web 模式：启动本地后端和前端页面，在浏览器中完成上传、配置、执行和导出。

核心原则：

- 两轮顺序固定为 `1 -> 2`，不能跳轮，不能合并执行。
- 每次调用只处理一轮。
- 单轮内部也必须先分块，再逐块改写，最后按原段落结构还原。
- 不新增事实、数据、文献、案例或结论。
- 保留原文术语、编号、逻辑关系和论文语体。

## 适用场景

适合以下任务：

- 中文论文去 AI 味
- 多轮降低 AIGC 痕迹
- 对长文档进行分段改写并保留原有结构
不适合以下任务：

- 长文件建议使用脚本，直接在聊天框效果不佳

## 效果
<img width="1910" height="915" alt="image" src="https://github.com/user-attachments/assets/356ec75b-52eb-4054-a5cd-25e986fc0245" />
 中文论文去 AI 味
 多轮降低 AIGC 痕迹
 对长文档进行分段改写并保留原有结构
 基于 `.docx` 和 `.txt` 的论文处理工作流

<img width="1910" height="915" alt="image" src="https://github.com/user-attachments/assets/c36e4a48-4192-4d78-ad3c-6c0787be1fa1" />
 一次性把两轮规则混合执行
 把整篇长文一次性整体重写
 为了“过检测”而随意改动事实或专业内容


## 目录结构

```text
.
├─ app/
│  ├─ index.html
│  ├─ package.json
│  ├─ tsconfig.json
│  ├─ vite.config.ts
│  └─ src/
│     ├─ App.tsx
│     ├─ main.tsx
│     ├─ components/
│     ├─ hooks/
│     ├─ lib/
│     ├─ styles/
│     └─ types/
├─ SKILL.md
├─ README.md
├─ requirements.txt
├─ origin/
├─ finish/
│  ├─ aigc_records.json
│  ├─ intermediate/
│  └─ web_exports/
├─ prompts/
│  ├─ baibaiAIGC1.md
│  └─ baibaiAIGC2.md
├─ references/
│  ├─ checklist.md
│  └─ usage.md
├─ src-tauri/
│  ├─ Cargo.toml
│  ├─ build.rs
│  ├─ tauri.conf.json
│  ├─ capabilities/
│  ├─ gen/
│  ├─ icons/
│  └─ src/
└─ scripts/
   ├─ aigc_records.py
   ├─ aigc_round_service.py
   ├─ app_config.py
   ├─ app_service.py
   ├─ chunking.py
   ├─ docx_pipeline.py
   ├─ llm_client.py
   ├─ run_aigc_round.py
   ├─ skill_round_helper.py
   └─ web_app.py
```

目录约定：

- `origin/`：放原始输入文件，通常是 `.txt` 或 `.docx`。
- `finish/intermediate/`：放每一轮的中间文本、提取文本和 manifest。
- `finish/web_exports/`：放 Web 端导出的 `.txt` 或 `.docx` 文件。
- `finish/`：放最终产物，以及 `aigc_records.json` 这类记录文件。
- `prompts/`：两轮提示词，严格按顺序使用。
- `references/`：使用说明和评分清单。
- `app/`：Web 前端与 Tauri 前端工程。
- `src-tauri/`：桌面端 Tauri 壳层。

安装依赖：

```powershell
pip install -r requirements.txt
```

Web 前端依赖安装：

```powershell
cd app
npm install
```

当前依赖非常少：

- `python-docx`：用于 `.docx` 文本提取和回写

## 快速开始
### 1. 准备输入文件

把待处理文件放到 `origin/` 目录。

示例：

- `origin/毕业论文.docx`
- `origin/毕业论文_原始_utf8.txt`

#### 模式 A：对话 skill 模式

适合直接在聊天中执行当前应进行的一轮改写。

特点：

- 不需要你手动配置 `API Key / Model / Base URL`
入口和约束见 [SKILL.md](SKILL.md)。

#### 模式 B：脚本 API 模式

适合用脚本做单轮批处理。

特点：


脚本入口是 [scripts/run_aigc_round.py](scripts/run_aigc_round.py)。

#### 模式 C：Web 模式

适合在浏览器中完成模型配置、文件上传、轮次执行和导出。

后端入口是 [scripts/web_app.py](scripts/web_app.py)，前端入口位于 [app/package.json](app/package.json)。

## Web 端运行说明

先启动 Python 后端：

```powershell
python scripts/web_app.py
```

再启动前端开发服务器：

```powershell
cd app
npm run dev:web
```

启动后按 Vite 终端输出中的本地地址在浏览器访问，前端会调用本地 Flask API。

Web 模式下可完成以下操作：

- 上传 `.txt` 或 `.docx` 文件到 `origin/`
- 配置并测试模型连接
- 按当前记录继续执行第 1 轮或第 2 轮
- 读取历史输出并导出 `.txt` 或 `.docx` 到 `finish/web_exports/`

## 脚本 API 模式用法

### 必填参数

运行单轮处理：

```powershell
python scripts/run_aigc_round.py <doc_id> <round> <input_path> <output_path> <manifest_path> [--chunk-limit 850]
```

- `output_path`：本轮输出文本路径
- `manifest_path`：本轮切块结构输出路径

### 配置模型 API
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

1. 优先按原始段落切分。
2. 若段落超过 850 字，再按完整句子的自然断句继续切分。
3. 不在句子中间、术语中间、编号中间截断。
4. 逐块处理完成后，必须按原段落顺序恢复。

默认单块上限为 `850` 字，可通过 `--chunk-limit` 调整。
评分标准见 [references/checklist.md](references/checklist.md)。

建议做两类检查：

1. 每一轮完成后做一次阶段性评分
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

### 4. 可以整篇一次性处理吗？

不可以。长文本必须分段分块处理。

## 推荐工作流

### 工作流 A：人工主导

1. 把 `.docx` 放进 `origin/`
2. 提取为 `.txt`
3. 在聊天中执行第 1 轮
4. 新开对话执行第 2 轮
5. 终检评分后写回 `.docx`

### 工作流 B：脚本主导

1. 准备 `.txt` 输入
2. 配置 API 环境变量
3. 依次执行第 1、2 轮脚本
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
## 🙏 致谢
感谢 [linuxdo（linux.do） ](https://linux.do/) 社区的交流、分享与反馈。
