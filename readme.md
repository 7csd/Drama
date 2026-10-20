# Drama · 短剧 AI 短剧生产工作台

基于 [ViMax](https://github.com/HKUDS/ViMax) 的本地短剧制作工作台，将已有剧本、角色与场景资产、分镜、配音、关键帧、逐镜视频、人工审片和交付串联起来。

支持动态漫和写实短剧两类风格。默认使用离线模拟模式，便于先体验制作流程；接入云模型后才能生成真实图像、声音和视频。

[详细使用说明](README_WORKBENCH.md) · [ViMax 原版说明](README_VIMAX.md) · [ViMax 中文说明](README_ZH.md) · [MIT 许可证](LICENSE)

## 主要功能

- **项目与分集管理**：维护剧本、风格、画幅、预算及生产进度。
- **资产与分镜**：管理角色、场景、道具和参考图，审阅并确认分镜。
- **逐镜生产**：编排配音、关键帧、视频和口型任务，先审样镜，再批量制作。
- **人工审核门禁**：检查人物身份、连续性、声音归属、对白完整性和口型同步。
- **任务与费用管理**：持久化队列、预算预占、任务状态和服务端任务 ID，支持部分异常恢复。
- **版本与交付**：修改资产或分镜后追踪过期产物，导出视频、字幕和素材清单。

## 快速开始

### 运行环境

- Python **3.12**（建议使用此版本）。
- Node.js **20 或更高版本**，包含 npm。
- 首次安装依赖需要联网。
- 离线演示不需要 API 密钥、独立显卡、MySQL、Redis 或 Docker。

### Windows PowerShell

克隆本仓库后，在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\start-workbench.ps1
```

脚本将创建 `.venv`、安装工作台依赖和前端依赖、构建页面，然后启动服务。

打开 **http://127.0.0.1:8787/drama** 。保留终端窗口，按 `Ctrl+C` 停止服务。

如需更换端口：

```powershell
powershell -ExecutionPolicy Bypass -File .\start-workbench.ps1 -Port 8788
```

若系统存在多个 Python 版本，请先确认 `python --version` 为 3.12，或自行用 Python 3.12 创建 `.venv`。

### 手动启动

Windows：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-workbench.txt
cd web
npm.cmd ci
npm.cmd run build
cd ..
.\.venv\Scripts\python.exe -m uvicorn workbench.api:app --host 127.0.0.1 --port 8787
```

Linux / macOS 可按以下命令安装和启动；本次迁移仅在 Windows 上完成验证：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-workbench.txt
(cd web && npm ci && npm run build)
.venv/bin/python -m uvicorn workbench.api:app --host 127.0.0.1 --port 8787
```

## 体验制作流程

点击页面中的“体验双风格示例”，按顺序操作：

1. 确认剧本，生成参考图。
2. 确认资产和分镜。
3. 生成样镜，逐镜审阅并确认。
4. 批量生产，审阅其余镜头。
5. 合成视频并下载交付文件。

**离线模式使用标注过的占位图、静音配音及模拟视频。它用于验证工作流，不代表真实生成质量。**

## 接入真实模型

真实生成需要额外安装 ViMax 依赖，并准备语言模型、图像、视频、配音和口型服务的账号及密钥。配置步骤见 [工作台说明：接入云服务](README_WORKBENCH.md#接入云服务)。

主要配置位置：

| 配置 | 用途 |
| --- | --- |
| `configs/drama.example.yaml` | 语言模型配置示例，复制为 `configs/drama.local.yaml` 后填写 |
| `.drama/providers.local.json` | 页面“模型与服务”保存的供应商、模型和费用上限 |
| `DRAMA_ENABLE_LIVE=1` | 启用真实服务，启动前设置并重启 |
| `FAL_KEY` | fal 图像、视频和口型服务密钥 |
| `DASHSCOPE_API_KEY` | CosyVoice 配音服务密钥 |
| `DRAMA_DATA_DIR` | 可选，自定义数据目录 |

`cost_ceiling_cny` 需要配置 `plan`、`asset_image`、`keyframe`、`tts`、`video`、`lipsync` 六项单次调用费用上限。真实调用会产生供应商费用，模型权限、接口兼容性、价格与成片质量需自行实测。

不要把密钥写入前端或提交到仓库。项目不会自动读取 `.env`；启动环境变量应在启动服务的终端中设置。

## 数据与部署范围

默认数据目录为 `.drama/`，其中保存 SQLite 数据库、媒体和本地服务配置。备份或迁移时，先停止服务，再复制完整数据目录；私有 YAML 配置需另行备份。

当前版本面向**本地内部制作**，没有多用户登录和权限系统。只运行一个 Uvicorn 工作进程；内部任务并发为 2，不要通过 `--workers` 扩容。

原版 ViMax Web 与短剧工作台入口不同。`cd web && npm run dev` 启动的是原版 Node 服务，不包含短剧后端。短剧开发热更新方式见 [工作台开发说明](README_WORKBENCH.md#开发与验证)。

## 项目结构

```text
workbench/                 短剧 API、任务引擎、数据库、媒体处理与供应商适配
web/src/DramaWorkbench.tsx 短剧制作界面
configs/                   示例配置
agent_runtime/             ViMax Agent 运行时
agents/ pipelines/ tools/  ViMax 规划与生成流程
requirements-workbench.txt 工作台 Python 依赖
start-workbench.ps1         Windows 安装与启动脚本
README_WORKBENCH.md         工作台完整操作说明
```

## 验证与开发

```powershell
.\.venv\Scripts\python.exe -m pytest workbench/tests -q
.\.venv\Scripts\python.exe -m workbench.smoke --data .drama-validation
cd web
npm.cmd test
npx.cmd tsc --noEmit
npm.cmd run build
```

2026-10-19 在 Windows、Python 3.12.14、Node.js 24.19.0 上验证：后端 26 项测试通过、1 项跳过，前端 35 项测试通过，类型检查与构建通过。离线验收完成 96 个任务，导出动态漫和写实各一份约 75.72 秒的占位样片，未调用云模型。

真实云服务的效果与完整生产成本尚未验收。人工审片仍是必要步骤。

## 来源与许可

本项目基于 `HKUDS/ViMax`，上游基础提交为 `fd4b72e7731be6e5f88486206d25ea59849b0285`；迁移包记录的项目来源为 `7csd/Drama`。保留上游源码、示例素材、文档和原 MIT 许可声明。

新增工作包括 `workbench/` 短剧工作流与持久任务、React 制作界面，以及画幅和缓存版本相关改动。上游说明保存在 [README_VIMAX.md](README_VIMAX.md) 与 [README_ZH.md](README_ZH.md)。

源码按 [MIT License](LICENSE) 提供。第三方模型服务及素材的使用仍需遵守其各自条款。
