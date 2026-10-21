# 短剧 · AI 短剧生产工作台

在 ViMax 上新增的内部制作工作台：已有剧本 → 角色／场景／道具 → 分镜 → 配音与关键帧 → 逐镜视频 → 口型 → 人工审片 → 字幕混音与交付。

## 本地启动

Windows PowerShell，在仓库根目录运行：

```powershell
.\start-workbench.ps1
```

打开 http://127.0.0.1:8787/drama 。默认完全离线模拟，无 API 调用。点击“体验双风格示例”创建两集；按生产流程确认剧本、生成参考图、确认资产及分镜、生成样镜、逐镜审片、确认样镜、批量生成、审完其余镜头后合成。

模拟图像为标注过的占位图，配音为静音，口型步骤复制占位视频。模拟审阅只用于检验流程，**不证明角色、对白、声音或口型质量**。云模式不会把模拟素材当成真实生产资产。

数据默认保存在 `.drama/`，可用 `DRAMA_DATA_DIR` 指向其他目录。数据库、素材、密钥配置均忽略提交。只启动一个工作进程；内置并发为 2，不要使用 uvicorn `--workers` 扩容。原版 ViMax Web 保留，可按 `web/README.md` 启动；其 Node 服务不包含短剧后端。

## 接入云服务

本轮没有调用付费服务，也没有真实短剧效果验收。实际使用前先验证供应商账号、模型权限、连通性与样镜质量。

1. 在同一个 Python 环境安装 ViMax 依赖：

```powershell
.\.venv\Scripts\python.exe -c "import tomllib,subprocess,sys; deps=tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']; subprocess.run([sys.executable,'-m','pip','install',*deps],check=True)"
```

2. 将 `configs/drama.example.yaml` 复制为 `configs/drama.local.yaml`（本机已创建模板）。所有模型调用配置统一放在这个 YAML：
   - `mode`：`mock` 离线模拟，`live` 真实付费调用。
   - `chat_model.init_args`：规划模型名称、协议、接口地址、API 密钥。
   - `fal_key`：fal 平台密钥；`image_model`、`image_edit_model`、`video_model`、`lipsync_models`：对应模型标识。fal 队列地址由适配器固定为 `https://queue.fal.run`。
   - `voice_model`、`cosyvoice_endpoint`、`dashscope_api_key`：配音模型、HTTP 地址和密钥。
   - `cost_ceiling_cny`：各类任务单次人民币费用上限。
3. 在页面“模型与服务”点击“重新加载 YAML 配置”，或重启服务。加载失败时保留原配置；修改配置后旧配置任务会暂停。不要在任务执行期间更换配置。

不再读取 `.drama/providers.local.json`，不再读取模型密钥或真实模式环境变量，也不自动加载 `.env`。旧用户需把配置手动移入上述 YAML。密钥不会返回到页面；本地 YAML 已被 Git 忽略。ViMax 仍调用 `plan_text_artifacts`，并校验原始说话人与对白。

`cost_ceiling_cny` 需要 `plan`、`asset_image`、`keyframe`、`tts`、`video`、`lipsync` 六项。每项是**一次提交的最高费用估算**，视频应覆盖 15 秒的最高规格，规划应覆盖 ViMax 的多次 LLM 调用，外币调用须自行折算人民币。预算按这个数预占，完成后暂计消耗，不能替代供应商侧账单或硬限额。用 `PATCH /api/drama/jobs/{id}/cost` 填入经账单核验的 `actual_cost`（人民币），包括失败任务与返工，才可计算真实每分钟成本。

当前 fal 适配器默认使用 Nano Banana、Seedance 2.0 Fast、LatentSync；CosyVoice 使用固定角色音色。模型名可配置，但所选接口须兼容已有请求参数。两种风格的口型模型分别配置，**动态漫适用性须独立验证**。双人对白须拆成每镜一个说话人；侧脸、遮挡、多人物、强动作可能需要人工改镜或换服务。服务输入/输出适配已实现，真实质量、服务版本兼容与价格仍需账号实测。

配音使用实际 WAV 时长安排画面；视频模型单镜最长 15 秒，超长对白会在提交视频前被阻止。机械检查覆盖可解码、画幅和时长；人物身份、连续性、声音归属、对白完整性、口型同步五项由人工审核，未实现自动语义审片。

接口参考：[fal 图片](https://fal.ai/models/fal-ai/nano-banana/edit/api)、[fal 视频](https://github.com/fal-ai/seedance-2.0-api)、[fal 口型](https://fal.ai/models/fal-ai/latentsync/api)、[CosyVoice HTTP](https://help.aliyun.com/zh/model-studio/cosyvoice-tts-http-api)。

## 续作、修改与异常处理

- SQLite 保存稳定 ID、版本、产物快照、审阅记录、服务任务 ID 和费用占用。重复排产复用相同输入任务。
- 修改分镜只让该镜头产物过期；修改资产只让引用该资产的镜头过期，跨集引用同样生效。旧产物仍可追溯。完成修改后需重新确认对应门禁。
- 队列中任务预算不足会暂停，提高项目预算后自动继续。限流最多自动重试两次。
- 有服务端任务 ID 的请求在重启后恢复查询；提交响应丢失且没有 ID 时进入“待核对”，占用预算，不自动重投。fal 任务可在任务页填写原始服务端 ID 恢复查询。CosyVoice/LLM 提交状态未知时暂保留预算，需人工核对供应商，不支持盲目自动重投。
- 当前任务模式或模型配置与排产时不一致会暂停；处理在途任务时恢复原配置。已经完成的任务历史仍保留。
- 源码中 ViMax 的关键帧尺寸可通过 `render_options.frame_size` 配置；剧本、风格、画幅变化后，其旧缓存归档到工作目录 `.history/`。工作台的逐镜缓存独立按版本追踪。

## 开发与验证

```powershell
# 后端
.\.venv\Scripts\python.exe -m uvicorn workbench.api:app --host 127.0.0.1 --port 8787
# 前端热更新（另一终端），访问 Vite 地址的 /drama
cd web
npx.cmd vite --host 127.0.0.1
```

Vite 将 `/api/drama` 代理到 8787；同源写入检查保留，反向代理需保持 Origin 与 Host 一致。该版本仅面向本地内部使用，无多用户认证或对外托管功能。

```powershell
.\.venv\Scripts\python.exe -m pytest workbench/tests -q
.\.venv\Scripts\python.exe -m workbench.smoke --data .drama-validation
cd web
npm.cmd test
npx.cmd tsc --noEmit
npm.cmd run build
```

离线验收使用真实 FFmpeg，分别导出约 75 秒的动态漫和写实**占位样片**，包含烧录字幕、独立 SRT、素材和生成清单 ZIP。验收脚本只构造本地模拟适配器，不访问云模型。

## 来源

项目仓库：[7csd/Drama](https://github.com/7csd/Drama)。ViMax 上游：`HKUDS/ViMax`，基础提交 `fd4b72e7731be6e5f88486206d25ea59849b0285`，保留原 MIT LICENSE、示例素材与基准数据。

本次新增：`workbench/` 持久任务与 API、`web/src/DramaWorkbench.tsx` 制作界面，以及上游关键帧画幅与缓存版本支持。没有复用非商业许可项目的代码。
