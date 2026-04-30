# baibaiAIGC
<div align="center">
   <img src="e7d4bdd094205b9e244508aca83e4d3a.png" alt="图片">
</div>
一个用于中文论文、摘要、课程作业和技术文档多轮降 AIGC 改写的工作目录。

本仓库支持四种使用方式：

1. 对话 skill 模式：在聊天中按 `SKILL.md` 约束执行单轮改写。
2. 脚本 API 模式：通过 `scripts/run_aigc_round.py` 执行单轮分段处理，并按需调用外部 OpenAI 兼容接口。
3. Web 模式：启动本地后端和前端页面，在浏览器中完成上传、配置、执行和导出。
4. app：安装app可直接使用

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

## 使用建议
* 推荐使用web端，然后是脚本，最后是当成skill（skill文本太长不稳定）

## 快速开始
### 1. 准备输入文件

把待处理文件放到 `origin/` 目录。

示例：

- `origin/毕业论文.docx`
- `origin/毕业论文_原始_utf8.txt`

#### 模式 A：使用app（点击下方链接）

[![点击下载baibaiAIGC](https://img.shields.io/badge/Download-Windows%20Installer-blue?style=for-the-badge&logo=windows)](https://github.com/poleHansen/baibaiAIGC/releases)

#### 模式 B：Web 模式

适合在浏览器中完成模型配置、文件上传、轮次执行和导出。

后端入口是 [scripts/web_app.py](scripts/web_app.py)，前端入口位于 [app/package.json](app/package.json)。

### 一键安装并启动前后端

如果你只是想把 Web 前后端环境一次性装好并启动，可以直接在仓库根目录运行：

```powershell
.\start-web.bat
```

这条命令会自动完成：

- 创建根目录 `.venv` Python 虚拟环境（如果还没有）
- 安装后端依赖 `requirements.txt`
- 安装前端依赖 `app/package.json`
- 分别启动后端 Flask 和前端 Vite 开发服务器

启动成功后可访问：

- 前端：`http://127.0.0.1:1420`
- 后端：`http://127.0.0.1:8765`

如果依赖已经装好，只想跳过安装、直接启动，可以运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_web_dev.ps1 -SkipInstall
```

#### 模式 C：脚本 API 模式

适合用脚本做单轮批处理。

特点：


脚本入口是 [scripts/run_aigc_round.py](scripts/run_aigc_round.py)。

#### 模式 D：对话 skill 模式

适合直接在聊天中执行当前应进行的一轮改写。

特点：

- 不需要你手动配置 `API Key / Model / Base URL`
入口和约束见 [SKILL.md](SKILL.md)。

## Web 端运行方式二（自己安装环境运行）

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
python scripts/run_aigc_round.py origin/毕业论文_原始_utf8.txt 1 origin/毕业论文_原始_utf8.txt finish/intermediate/毕业论文_原始_utf8_round1.txt finish/intermediate/毕业论文_原始_utf8_round1_manifest.json --prompt-profile cn --chunk-limit 850
```

### 第 2 轮示例

```powershell
python scripts/run_aigc_round.py origin/毕业论文_原始_utf8.txt 2 finish/intermediate/毕业论文_原始_utf8_round1.txt finish/intermediate/毕业论文_原始_utf8_round2.txt finish/intermediate/毕业论文_原始_utf8_round2_manifest.json --prompt-profile cn --chunk-limit 850
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


## 常见问题

### 1. 为什么脚本执行时报缺少 API 配置？

因为 [scripts/run_aigc_round.py](scripts/run_aigc_round.py) 的自动改写依赖外部 OpenAI 兼容接口。

解决方法：

- 配置 `BAIBAIAIGC_API_KEY`
- 配置 `BAIBAIAIGC_MODEL`
- 配置 `BAIBAIAIGC_BASE_URL`

或者使用 `--dry-run` 只做切块校验。


## 说明

这个 README 面向后续使用者，目的是让使用方式、目录约定和执行边界一次说清。更严格的行为约束以 [SKILL.md](SKILL.md) 为准。
## 致谢
感谢 [linuxdo（linux.do） ](https://linux.do/) 社区的交流、分享与反馈。
## Star History

<a href="https://www.star-history.com/?repos=poleHansen%2FbaibaiAIGC&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=poleHansen/baibaiAIGC&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=poleHansen/baibaiAIGC&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=poleHansen/baibaiAIGC&type=date&legend=top-left" />
 </picture>
</a>
