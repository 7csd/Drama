import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronRight,
  Clapperboard,
  Clock3,
  Download,
  Film,
  Folder,
  Image as ImageIcon,
  Layers3,
  LoaderCircle,
  Plus,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Sparkles,
  Upload,
  Volume2,
  X,
} from "lucide-react";
import type {
  Asset,
  Episode,
  Gate,
  Health,
  Job,
  Project,
  Shot,
  Snapshot,
  Style,
} from "./dramaTypes";
import "./drama.css";
import { reviewIsCurrent } from "./dramaPresentation";

const ROOT = "/api/drama";
const STYLE = { comic: "动态漫", realistic: "写实短剧" };
const GATES: [Gate, string][] = [
  ["script", "剧本确认"],
  ["assets", "资产确认"],
  ["storyboard", "分镜确认"],
  ["sample", "样镜确认"],
];
const OPS: Record<string, string> = {
  plan: "剧本拆解",
  asset_image: "资产图",
  keyframe: "关键帧",
  tts: "角色配音",
  video: "视频生成",
  lipsync: "口型同步",
  qc: "机械检查",
  compose: "成片合成",
};
const STATUS: Record<string, string> = {
  queued: "排队中",
  running: "处理中",
  submitted: "服务端处理中",
  succeeded: "已完成",
  failed: "失败",
  paused: "已暂停",
  reconcile: "待核对",
  obsolete: "已过期",
  blocked: "依赖受阻",
  cancelled: "已取消",
};
const FRAMING: Record<string, string> = {
  closeup: "近景对白",
  two_shot: "双人对话",
  profile: "侧脸",
  action: "动作",
  transition: "场景切换",
};
const CHECKS = [
  ["identity", "人物身份"],
  ["continuity", "画面连续性"],
  ["voice", "声音归属"],
  ["dialogue", "对白完整性"],
  ["lip_sync", "口型同步"],
] as const;
const money = (value: number) => `¥${value.toFixed(2)}`;
const media = (path?: string) =>
  path
    ? `${ROOT}/media/${path.replaceAll("\\", "/").split("/").map(encodeURIComponent).join("/")}`
    : "";

async function api<T = unknown>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(`${ROOT}${path}`, {
    method,
    headers:
      body instanceof FormData || body === undefined
        ? {}
        : { "Content-Type": "application/json" },
    body:
      body instanceof FormData
        ? body
        : body === undefined
          ? undefined
          : JSON.stringify(body),
  });
  if (!response.ok) {
    let message = `请求失败 (${response.status})`;
    try {
      const data = await response.json();
      message =
        typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail);
    } catch {
      /* use status */
    }
    throw new Error(message);
  }
  return response.json();
}

function IconButton({
  children,
  onClick,
  title,
}: {
  children: ReactNode;
  onClick: () => void;
  title: string;
}) {
  return (
    <button
      className="dw-icon"
      title={title}
      aria-label={title}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

export default function DramaWorkbench() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [data, setData] = useState<Snapshot>();
  const [episodeId, setEpisodeId] = useState("");
  const [health, setHealth] = useState<Health>();
  const [tab, setTab] = useState("overview");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [modal, setModal] = useState<
    "project" | "episode" | "settings" | "budget" | "asset" | null
  >(null);
  const [editingShot, setEditingShot] = useState<Shot>();
  const [editingAsset, setEditingAsset] = useState<Asset>();
  const [reviewShot, setReviewShot] = useState<Shot>();
  const [history, setHistory] = useState<unknown[] | null>(null);
  const selectedRef = useRef(projectId);
  selectedRef.current = projectId;

  async function refresh(id = selectedRef.current) {
    if (!id) return;
    const snapshot = await api<Snapshot>(`/projects/${id}`);
    if (selectedRef.current !== id) return;
    setData(snapshot);
    setEpisodeId((current) =>
      snapshot.episodes.some((e) => e.id === current)
        ? current
        : snapshot.episodes[0]?.id || "",
    );
  }

  useEffect(() => {
    document.title = "短剧 · AI 短剧工作台";
    document.documentElement.lang = "zh-CN";
    Promise.all([api<Project[]>("/projects"), api<Health>("/health")])
      .then(([items, state]) => {
        setProjects(items);
        setHealth(state);
        setProjectId(items[0]?.id || "");
      })
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    setData(undefined);
    refresh(projectId).catch((e) => setError(e.message));
    const timer = setInterval(() => {
      if (!document.hidden)
        refresh(projectId).catch((e) => setError(e.message));
    }, 2000);
    return () => clearInterval(timer);
  }, [projectId]);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 3500);
    return () => clearTimeout(t);
  }, [toast]);

  async function action(task: () => Promise<unknown>, message = "已保存") {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await task();
      await refresh();
      setToast(message);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function demo() {
    await action(async () => {
      const project = await api<Project>("/projects", "POST", {
        name: "旧信 · 双风格样片",
        budget: 50,
      });
      const { script } = await api<{ script: string }>("/demo-script");
      for (const style of ["comic", "realistic"] as Style[]) {
        const ep = await api<Episode>(
          `/projects/${project.id}/episodes`,
          "POST",
          {
            title: `第一集 · ${STYLE[style]}`,
            style,
            script,
            target_duration: 75,
            aspect: "9:16",
          },
        );
        await api(`/episodes/${ep.id}/plan`, "POST");
      }
      setProjects(await api<Project[]>("/projects"));
      setProjectId(project.id);
      setTab("overview");
    }, "示例已建立，正在拆解剧本");
  }

  const episode = data?.episodes.find((e) => e.id === episodeId);
  const shots = (data?.shots || [])
    .filter((s) => s.episode_id === episodeId)
    .sort((a, b) => a.order - b.order);
  const jobs = (data?.jobs || []).filter((j) => j.episode_id === episodeId);
  const activeJobs = jobs.filter((j) =>
    ["queued", "running", "submitted"].includes(j.status),
  );
  const assets = (data?.assets || []).filter((a) => a.style === episode?.style);
  const passed = shots.filter((s) =>
    data?.reviews.some((r) => reviewIsCurrent(s, r)),
  ).length;
  const plannedDuration = shots.reduce(
    (total, s) => total + (s.outputs.qc?.duration || s.duration),
    0,
  );
  const currentGate = episode
    ? GATES.find(([key]) => !episode.gates[key])
    : undefined;
  const approve = (gate: Gate) =>
    action(
      () => api(`/episodes/${episodeId}/approve/${gate}`, "POST"),
      "审阅确认已记录",
    );
  const run = (phase: string) =>
    action(
      () => api(`/episodes/${episodeId}/run`, "POST", { phase }),
      "已排入生产队列",
    );

  return (
    <div className="drama">
      <aside className="dw-sidebar">
        <a className="dw-brand" href="/drama">
          <span className="dw-logo">
            <Clapperboard size={23} />
          </span>
          <span>
            短剧<small>DRAMA WORKSPACE</small>
          </span>
        </a>
        <div className="dw-space-label">
          创作空间 <span>INTERNAL</span>
        </div>
        <button className="dw-new-project" onClick={() => setModal("project")}>
          <Plus size={17} /> 新建项目
        </button>
        <div className="dw-project-heading">
          我的项目 <span>{projects.length.toString().padStart(2, "0")}</span>
        </div>
        <nav className="dw-project-list">
          {projects.map((p) => (
            <button
              key={p.id}
              className={projectId === p.id ? "selected" : ""}
              onClick={() => {
                setProjectId(p.id);
                setTab("overview");
              }}
            >
              <Folder size={17} />
              <span>{p.name}</span>
              {projectId === p.id && <span className="dw-dot" />}
            </button>
          ))}
        </nav>
        <div className="dw-side-bottom">
          <div className="dw-side-note">
            <ShieldCheck size={18} />
            <p>
              每一步，都可回溯<small>审阅 · 版本 · 任务记录</small>
            </p>
          </div>
          <button onClick={() => setModal("settings")}>
            <Settings2 size={17} /> 模型与服务 <ChevronRight size={14} />
          </button>
          <div className="dw-user">
            <span>创</span>
            <div>
              内部制作团队<small>本地工作空间</small>
            </div>
            <span className="dw-online" />
          </div>
        </div>
      </aside>

      <main className="dw-main">
        <header className="dw-topbar">
          <div>
            <Layers3 size={15} />
            <span>创作空间</span>
            <ChevronRight size={13} />
            <strong>{data?.project.name || "项目总览"}</strong>
          </div>
          <div>
            <span
              className={`dw-mode ${health?.mode === "live" ? "live" : ""}`}
            >
              <span className="dw-dot" />
              {health?.mode === "live" ? "云模型生产" : "本地模拟模式"}
            </span>
            <IconButton
              title="刷新"
              onClick={() => {
                refresh().catch((e) => setError(e.message));
              }}
            >
              <RefreshCw size={16} />
            </IconButton>
          </div>
        </header>
        {error && (
          <div className="dw-error" role="alert">
            <span>{error}</span>
            <IconButton title="关闭错误" onClick={() => setError("")}>
              <X size={16} />
            </IconButton>
          </div>
        )}
        <div className="dw-content">
          <section className="dw-page-heading">
            <div>
              <div className="dw-eyebrow">STORY TO SCREEN</div>
              <h1>{data?.project.name || "把故事，推进到成片。"}</h1>
              <p>
                {data
                  ? "让每一个镜头有依据，让每一次创作可掌控。"
                  : "剧本、角色、分镜与成片，在同一个工作空间有序发生。"}
              </p>
            </div>
            <button
              className="dw-primary"
              disabled={busy}
              onClick={() => setModal(data ? "episode" : "project")}
            >
              <Plus size={17} />
              {data ? "导入新剧集" : "创建第一个项目"}
            </button>
          </section>
          {!data && !projectId ? (
            <section className="dw-empty-hero">
              <div className="dw-film-mark">
                <Film size={60} strokeWidth={1} />
              </div>
              <span className="dw-eyebrow">YOUR NEXT STORY STARTS HERE</span>
              <h2>从一份剧本，开始下一部作品</h2>
              <p>
                支持动态漫与写实短剧。关键节点由你确认，
                <br />
                生成、检查与返工交给生产流程。
              </p>
              <div className="dw-actions">
                <button
                  className="dw-primary"
                  disabled={busy || !health || health.mode === "live"}
                  onClick={demo}
                >
                  <Sparkles size={17} /> 体验双风格示例
                </button>
                <button
                  className="dw-secondary"
                  onClick={() => setModal("project")}
                >
                  导入我的故事 <ArrowRight size={16} />
                </button>
              </div>
              <small>
                示例使用本地占位素材，无 API
                调用或生成费用。云模式下请新建真实项目。
              </small>
              <div className="dw-feature-strip">
                <span>
                  <ImageIcon size={19} /> 统一角色资产
                </span>
                <span>
                  <Clapperboard size={19} /> 逐镜审阅与返工
                </span>
                <span>
                  <ShieldCheck size={19} /> 预算与版本可追踪
                </span>
              </div>
            </section>
          ) : !data ? (
            <div className="dw-loading">
              <LoaderCircle className="dw-spin" /> 正在读取项目…
            </div>
          ) : (
            <>
              <section className="dw-stats">
                <Stat
                  label="项目预算余额"
                  value={money(data.budget.remaining)}
                  sub={`占用 ${money(data.budget.reserved)} · 消耗上限估算 ${money(data.budget.spent_ceiling)}`}
                  onClick={() => setModal("budget")}
                />
                <Stat
                  label="当前剧集"
                  value={`${shots.length.toString().padStart(2, "0")} 镜`}
                  sub={`${episode ? STYLE[episode.style] : "等待导入"} · ${episode?.aspect || "9:16"} · 720p`}
                />
                <Stat
                  label="计划成片时长"
                  value={`${plannedDuration.toFixed(1)} 秒`}
                  sub="目标 60—90 秒 · 对白时长优先"
                />
                <Stat
                  label="人工审片进度"
                  value={`${passed} / ${shots.length}`}
                  sub={`${activeJobs.length} 个任务进行中`}
                />
              </section>
              <div className="dw-episode-bar">
                <div>
                  <span className="dw-section-caption">当前剧集</span>
                  <select
                    aria-label="选择剧集"
                    value={episodeId}
                    onChange={(e) => setEpisodeId(e.target.value)}
                  >
                    {data.episodes.map((ep) => (
                      <option key={ep.id} value={ep.id}>
                        {ep.title} · {STYLE[ep.style]}
                      </option>
                    ))}
                  </select>
                  <span className="dw-tag">{episode?.aspect || "9:16"}</span>
                </div>
                <span className="dw-muted">已自动保存到本地</span>
              </div>
              <nav className="dw-tabs">
                {[
                  ["overview", "生产总览"],
                  ["assets", "角色与场景"],
                  ["storyboard", "分镜工作台"],
                  ["jobs", "任务与费用"],
                  ["delivery", "成片交付"],
                ].map(([id, title]) => (
                  <button
                    key={id}
                    className={tab === id ? "active" : ""}
                    onClick={() => setTab(id)}
                  >
                    {title}
                    {id === "jobs" && activeJobs.length > 0 && (
                      <span>{activeJobs.length}</span>
                    )}
                  </button>
                ))}
              </nav>
              {health?.mode !== "live" && (
                <div className="dw-notice">
                  <Sparkles size={15} />
                  <span>
                    当前为流程模拟：图片为占位图，配音为静音，未执行真实口型同步。审阅记录仅用于验证工作流。
                  </span>
                </div>
              )}
              {!episode ? (
                <div className="dw-panel dw-empty">
                  <h3>还没有剧集</h3>
                  <p>导入剧本，选择一种风格开始制作。</p>
                  <button
                    className="dw-primary"
                    onClick={() => setModal("episode")}
                  >
                    导入新剧集
                  </button>
                </div>
              ) : (
                <>
                  {tab === "overview" && (
                    <div className="dw-overview-grid">
                      <section className="dw-panel">
                        <div className="dw-panel-title">
                          <h2>生产流程</h2>
                          <span className="dw-muted">PRODUCTION FLOW</span>
                        </div>
                        <div className="dw-pipeline">
                          {[
                            [
                              "01",
                              "剧本与节拍",
                              "整理人物、场景与对白",
                              episode.gates.script,
                              () => approve("script"),
                              "确认剧本",
                            ],
                            [
                              "02",
                              "角色与场景",
                              "建立参考图与固定音色",
                              episode.gates.assets,
                              () => setTab("assets"),
                              "准备资产",
                            ],
                            [
                              "03",
                              "分镜与预览",
                              "确定构图、时长和镜头内容",
                              episode.gates.storyboard,
                              () => setTab("storyboard"),
                              "审阅分镜",
                            ],
                            [
                              "04",
                              "样镜验证",
                              "检查人物、声音和口型",
                              episode.gates.sample,
                              () => run("sample"),
                              "生成样镜",
                            ],
                            [
                              "05",
                              "批量生产",
                              "逐镜生成、检查与返工",
                              passed === shots.length && shots.length > 0,
                              () => run("full"),
                              "批量生成",
                            ],
                            [
                              "06",
                              "合成与交付",
                              "统一字幕、响度与成片规格",
                              !!episode.delivery,
                              () => run("compose"),
                              "合成成片",
                            ],
                          ].map(([num, title, desc, done, click, label]) => (
                            <div
                              className={`dw-step ${done ? "done" : ""}`}
                              key={num as string}
                            >
                              <span className="dw-step-number">
                                {done ? <Check size={16} /> : (num as string)}
                              </span>
                              <div>
                                <h3>{title as string}</h3>
                                <p>{desc as string}</p>
                              </div>
                              <button
                                disabled={busy || !shots.length}
                                onClick={click as () => void}
                              >
                                {done ? "已完成" : (label as string)}
                                <ChevronRight size={13} />
                              </button>
                            </div>
                          ))}
                        </div>
                      </section>
                      <div className="dw-overview-right">
                        <section className="dw-panel">
                          <div className="dw-panel-title">
                            <h2>剧本原文</h2>
                            <span className="dw-tag">
                              {STYLE[episode.style]}
                            </span>
                          </div>
                          <pre className="dw-script">{episode.script}</pre>
                          <div className="dw-panel-footer">
                            <button
                              className="dw-secondary"
                              disabled={
                                busy ||
                                shots.length > 0 ||
                                jobs.some(
                                  (j) =>
                                    j.op === "plan" &&
                                    ["queued", "running"].includes(j.status),
                                )
                              }
                              onClick={() =>
                                action(
                                  () =>
                                    api(`/episodes/${episode.id}/plan`, "POST"),
                                  "正在拆解剧本",
                                )
                              }
                            >
                              <Sparkles size={15} /> 拆解剧本
                            </button>
                            <button
                              className="dw-text-button"
                              onClick={() => setModal("episode")}
                            >
                              导入新版本
                            </button>
                          </div>
                        </section>
                        <section className="dw-next-card">
                          <span className="dw-eyebrow">NEXT UP</span>
                          <h3>
                            {currentGate ? currentGate[1] : "继续生成与审片"}
                          </h3>
                          <p>
                            剧本与参考资产经你确认后进入生产。每次修改都会保留版本，并更新受影响镜头。
                          </p>
                          <button
                            onClick={() =>
                              setTab(
                                currentGate?.[0] === "assets"
                                  ? "assets"
                                  : "storyboard",
                              )
                            }
                          >
                            进入工作台 <ArrowRight size={17} />
                          </button>
                        </section>
                      </div>
                    </div>
                  )}
                  {tab === "assets" && (
                    <>
                      <div className="dw-section-toolbar">
                        <div>
                          <h2>为故事建立稳定的视觉记忆</h2>
                          <p>
                            同风格角色可跨集复用。修改设定或参考图后，相关镜头需重新确认。
                          </p>
                        </div>
                        <div className="dw-actions">
                          <button
                            className="dw-secondary"
                            onClick={() => setModal("asset")}
                          >
                            <Plus size={16} /> 新建资产
                          </button>
                          <button
                            className="dw-secondary"
                            disabled={busy || !episode.gates.script}
                            onClick={() => run("assets")}
                          >
                            <Sparkles size={16} /> 生成缺失参考图
                          </button>
                          <button
                            className="dw-primary"
                            disabled={
                              busy || !assets.length || !episode.gates.script
                            }
                            onClick={() => approve("assets")}
                          >
                            <ShieldCheck size={16} /> 确认资产
                          </button>
                        </div>
                      </div>
                      <div className="dw-asset-grid">
                        {assets.map((asset) => (
                          <article className="dw-asset-card" key={asset.id}>
                            <button
                              className="dw-asset-preview"
                              onClick={() => setEditingAsset(asset)}
                            >
                              {asset.image ? (
                                <img
                                  src={media(asset.image)}
                                  alt={asset.name}
                                />
                              ) : (
                                <div>
                                  <ImageIcon size={32} strokeWidth={1} />
                                  <span>等待参考图</span>
                                </div>
                              )}
                              <span className="dw-preview-label">
                                {
                                  {
                                    character: "CHARACTER",
                                    scene: "SCENE",
                                    prop: "PROP",
                                  }[asset.kind]
                                }{" "}
                                · V{asset.version}
                              </span>
                            </button>
                            <div className="dw-asset-info">
                              <h3>
                                {asset.name}
                                <span>
                                  {
                                    {
                                      character: "角色",
                                      scene: "场景",
                                      prop: "道具",
                                    }[asset.kind]
                                  }
                                </span>
                              </h3>
                              <p>{asset.description}</p>
                              {asset.kind === "character" && (
                                <small>
                                  <Volume2 size={12} /> {asset.voice}
                                </small>
                              )}
                              <div className="dw-card-actions">
                                <button onClick={() => setEditingAsset(asset)}>
                                  编辑设定
                                </button>
                                <label className="dw-upload">
                                  上传参考图
                                  <input
                                    type="file"
                                    accept="image/png,image/jpeg,image/webp"
                                    onChange={(e) => {
                                      const f = e.target.files?.[0];
                                      if (f) {
                                        const form = new FormData();
                                        form.append("file", f);
                                        action(
                                          () =>
                                            api(
                                              `/assets/${asset.id}/image`,
                                              "POST",
                                              form,
                                            ),
                                          "参考图已更新",
                                        );
                                      }
                                    }}
                                  />
                                </label>
                              </div>
                            </div>
                          </article>
                        ))}
                      </div>
                      {!assets.length && (
                        <div className="dw-panel dw-empty">
                          先在生产总览拆解剧本，生成资产清单。
                        </div>
                      )}
                    </>
                  )}
                  {tab === "storyboard" && (
                    <>
                      <div className="dw-section-toolbar">
                        <div>
                          <h2>每一镜，都有清晰的创作意图</h2>
                          <p>
                            已选 {shots.filter((s) => s.sample).length} 个样镜 ·
                            点击镜头可编辑 · 生成后逐镜审片
                          </p>
                        </div>
                        <div className="dw-actions">
                          <button
                            className="dw-secondary"
                            disabled={busy || !episode.gates.assets}
                            onClick={() => approve("storyboard")}
                          >
                            <CheckCircle2 size={16} /> 确认分镜
                          </button>
                          <button
                            className="dw-primary"
                            disabled={busy || !episode.gates.storyboard}
                            onClick={() => run("sample")}
                          >
                            <Sparkles size={16} /> 生成样镜
                          </button>
                          <button
                            className="dw-secondary"
                            disabled={busy || !episode.gates.storyboard}
                            onClick={() => approve("sample")}
                          >
                            确认样镜
                          </button>
                          <button
                            className="dw-secondary"
                            disabled={busy || !episode.gates.sample}
                            onClick={() => run("full")}
                          >
                            批量生成
                          </button>
                        </div>
                      </div>
                      <div className="dw-storyboard-grid">
                        {shots.map((shot) => {
                          const video =
                            shot.outputs.lipsync || shot.outputs.video;
                          const review = data.reviews.find(
                            (r) => r.id === shot.review_id,
                          );
                          const reviewed = reviewIsCurrent(shot, review);
                          return (
                            <article className="dw-shot-card" key={shot.id}>
                              <div className="dw-shot-media">
                                {video?.path ? (
                                  <video
                                    controls
                                    preload="metadata"
                                    src={media(video.path)}
                                    poster={media(shot.outputs.keyframe?.path)}
                                  />
                                ) : shot.outputs.keyframe?.path ? (
                                  <img
                                    src={media(shot.outputs.keyframe.path)}
                                    alt={`镜头 ${shot.order + 1}`}
                                  />
                                ) : (
                                  <button onClick={() => setEditingShot(shot)}>
                                    <Clapperboard size={29} strokeWidth={1} />
                                    <span>等待关键帧</span>
                                  </button>
                                )}
                                <span className="dw-shot-id">
                                  {(shot.order + 1).toString().padStart(2, "0")}{" "}
                                  <small>SHOT</small>
                                </span>
                                {shot.sample && (
                                  <span className="dw-sample-badge">样镜</span>
                                )}
                              </div>
                              <div className="dw-shot-info">
                                <div className="dw-shot-title">
                                  <h3>
                                    {FRAMING[shot.framing] || shot.framing}
                                  </h3>
                                  <span>
                                    <Clock3 size={12} />
                                    {(
                                      shot.outputs.qc?.duration || shot.duration
                                    ).toFixed(1)}
                                    s
                                  </span>
                                </div>
                                <p>{shot.visual}</p>
                                <blockquote>
                                  {shot.dialogue || "无对白 · 环境与动作镜头"}
                                </blockquote>
                                {shot.outputs.tts?.path && (
                                  <audio
                                    controls
                                    preload="none"
                                    src={media(shot.outputs.tts.path)}
                                  />
                                )}
                                <div className="dw-card-actions">
                                  <button onClick={() => setEditingShot(shot)}>
                                    编辑 / 重做 <span>V{shot.version}</span>
                                  </button>
                                  <button
                                    disabled={
                                      !shot.outputs.qc?.mechanical_passed
                                    }
                                    onClick={() => setReviewShot(shot)}
                                    className={reviewed ? "dw-passed" : ""}
                                  >
                                    {reviewed ? "已审片 ✓" : "人工审片"}
                                  </button>
                                </div>
                              </div>
                            </article>
                          );
                        })}
                      </div>
                    </>
                  )}
                  {tab === "jobs" && (
                    <>
                      <div className="dw-section-toolbar">
                        <div>
                          <h2>生产记录，每一步有迹可循</h2>
                          <p>
                            费用使用配置上限估算，包含失败和返工。服务未返回账单时，实际费用显示为待核对。
                          </p>
                        </div>
                        <button
                          className="dw-secondary"
                          onClick={() => setModal("budget")}
                        >
                          调整项目预算
                        </button>
                      </div>
                      <div className="dw-panel dw-table-wrap">
                        <table className="dw-table">
                          <thead>
                            <tr>
                              <th>任务 / 版本</th>
                              <th>阶段</th>
                              <th>状态</th>
                              <th>尝试</th>
                              <th>占用 / 消耗估算</th>
                              <th>实际费用</th>
                              <th>操作</th>
                            </tr>
                          </thead>
                          <tbody>
                            {[...jobs].reverse().map((job) => (
                              <tr key={job.id}>
                                <td>
                                  <code>{job.id.slice(0, 8)}</code>
                                  <small>
                                    V{job.entity_version} ·{" "}
                                    {job.provider_mode === "mock"
                                      ? "模拟"
                                      : "云服务"}
                                  </small>
                                </td>
                                <td>{OPS[job.op]}</td>
                                <td>
                                  <span className={`dw-status ${job.status}`}>
                                    {STATUS[job.status] || job.status}
                                  </span>
                                  {job.error && (
                                    <p
                                      className="dw-job-error"
                                      title={job.error}
                                    >
                                      {job.error}
                                    </p>
                                  )}
                                  {job.remote && (
                                    <small>
                                      服务 ID: {job.remote.request_id}
                                    </small>
                                  )}
                                </td>
                                <td>{job.attempts}</td>
                                <td>
                                  {money(job.reserved)} / {money(job.spent)}
                                </td>
                                <td>
                                  {job.actual_cost == null ? (
                                    <CostReconcile
                                      job={job}
                                      busy={busy}
                                      action={action}
                                    />
                                  ) : (
                                    money(job.actual_cost)
                                  )}
                                </td>
                                <td>
                                  {job.status === "failed" && (
                                    <button
                                      className="dw-text-button"
                                      disabled={busy || job.attempts >= 3}
                                      onClick={() =>
                                        action(
                                          () =>
                                            api(
                                              `/jobs/${job.id}/retry`,
                                              "POST",
                                            ),
                                          "任务已重新排队",
                                        )
                                      }
                                    >
                                      重试
                                    </button>
                                  )}
                                  {job.status === "reconcile" && (
                                    <Reconcile
                                      job={job}
                                      busy={busy}
                                      action={action}
                                    />
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        {!jobs.length && (
                          <div className="dw-empty">
                            暂无任务，确认剧本后开始生产。
                          </div>
                        )}
                      </div>
                    </>
                  )}
                  {tab === "delivery" && (
                    <div className="dw-delivery-grid">
                      <section className="dw-panel dw-delivery-preview">
                        {episode.delivery?.path ? (
                          <video controls src={media(episode.delivery.path)} />
                        ) : (
                          <div className="dw-empty">
                            <Film size={50} strokeWidth={1} />
                            <h3>你的故事，即将在这里成片</h3>
                            <p>完成全部镜头审片后，合成统一规格的竖屏短剧。</p>
                            <button
                              className="dw-primary"
                              disabled={
                                busy ||
                                passed !== shots.length ||
                                !shots.length ||
                                !episode.gates.sample
                              }
                              onClick={() => run("compose")}
                            >
                              合成成片
                            </button>
                          </div>
                        )}
                      </section>
                      <section className="dw-panel">
                        <div className="dw-panel-title">
                          <h2>交付清单</h2>
                          <span className="dw-tag">
                            {episode.delivery?.simulated
                              ? "模拟样片"
                              : "DELIVERY"}
                          </span>
                        </div>
                        <div className="dw-delivery-details">
                          <p>
                            <span>画面规格</span>
                            <strong>{episode.aspect} · 720p · 24fps</strong>
                          </p>
                          <p>
                            <span>当前时长</span>
                            <strong>
                              {(
                                episode.delivery?.duration || plannedDuration
                              ).toFixed(1)}{" "}
                              秒
                            </strong>
                          </p>
                          <p>
                            <span>人工审片</span>
                            <strong>
                              {passed} / {shots.length}
                            </strong>
                          </p>
                          <p>
                            <span>合格成片每分钟成本</span>
                            <strong>
                              {episode.delivery &&
                              !episode.delivery.simulated &&
                              data.budget.unreconciled === 0
                                ? money(
                                    jobs.reduce(
                                      (s, j) => s + (j.actual_cost || 0),
                                      0,
                                    ) /
                                      (episode.delivery.duration! / 60),
                                  )
                                : "待真实样片与账单核验"}
                            </strong>
                          </p>
                        </div>
                        <div className="dw-downloads">
                          {episode.delivery?.path && (
                            <a
                              href={media(episode.delivery.path)}
                              download="final.mp4"
                            >
                              <Film size={17} /> 成片 MP4 <Download size={15} />
                            </a>
                          )}
                          {episode.delivery?.subtitles && (
                            <a
                              href={media(episode.delivery.subtitles)}
                              download="subtitles.srt"
                            >
                              <Layers3 size={17} /> 字幕 SRT{" "}
                              <Download size={15} />
                            </a>
                          )}
                          {episode.delivery?.bundle && (
                            <a
                              href={media(episode.delivery.bundle)}
                              download="delivery.zip"
                            >
                              <Folder size={17} /> 素材与项目清单 ZIP{" "}
                              <Download size={15} />
                            </a>
                          )}
                        </div>
                        <p className="dw-footnote">
                          项目包保留生成输入、模型参数、素材、版本及审阅记录。模拟成片用于验证流程，不代表模型质量。
                        </p>
                      </section>
                    </div>
                  )}
                </>
              )}
            </>
          )}
          <footer className="dw-footer">
            <span>短剧 / DRAMA</span>
            <span>基于 ViMax · 创作由你掌舵</span>
          </footer>
        </div>
      </main>
      {toast && (
        <div className="dw-toast" role="status">
          <CheckCircle2 size={17} />
          {toast}
        </div>
      )}
      {busy && (
        <div className="dw-busy" aria-live="polite">
          <LoaderCircle className="dw-spin" size={16} /> 正在处理…
        </div>
      )}
      {modal && (
        <Modal
          title={
            {
              project: "新建创作项目",
              episode: "导入新剧集",
              settings: "模型与服务",
              budget: "调整项目预算",
              asset: "新建角色、场景或道具",
            }[modal]
          }
          close={() => setModal(null)}
        >
          {modal === "asset" && episode && data && (
            <NewAssetForm
              style={episode.style}
              busy={busy}
              submit={(values) =>
                action(async () => {
                  await api(
                    `/projects/${data.project.id}/assets`,
                    "POST",
                    values,
                  );
                  setModal(null);
                }, "资产已建立，可在分镜中绑定")
              }
            />
          )}
          {modal === "project" && (
            <ProjectForm
              busy={busy}
              submit={async (values) => {
                await action(async () => {
                  const project = await api<Project>(
                    "/projects",
                    "POST",
                    values,
                  );
                  setProjects(await api<Project[]>("/projects"));
                  setProjectId(project.id);
                  setModal(null);
                }, "项目已创建");
              }}
            />
          )}
          {modal === "episode" && data && (
            <EpisodeForm
              busy={busy}
              submit={(values) =>
                action(async () => {
                  const styles =
                    values.style === "both"
                      ? ["comic", "realistic"]
                      : [values.style];
                  for (const style of styles) {
                    const ep = await api<Episode>(
                      `/projects/${data.project.id}/episodes`,
                      "POST",
                      { ...values, style },
                    );
                    setEpisodeId(ep.id);
                  }
                  setModal(null);
                  setTab("overview");
                }, "剧集已导入，请拆解并确认剧本")
              }
            />
          )}
          {modal === "budget" && data && (
            <ProjectForm
              busy={busy}
              project={data.project}
              submit={(values) =>
                action(async () => {
                  await api(`/projects/${data.project.id}`, "PATCH", values);
                  setProjects(await api<Project[]>("/projects"));
                  setModal(null);
                }, "预算已更新，暂停任务将自动检查余额")
              }
            />
          )}
          {modal === "settings" && (
            <Settings
              health={health}
              busy={busy}
              submit={(value) =>
                action(async () => {
                  await api("/config", "PUT", JSON.parse(value));
                  setHealth(await api<Health>("/health"));
                  setModal(null);
                }, "服务配置已保存")
              }
            />
          )}
        </Modal>
      )}
      {editingShot && (
        <Modal
          title={`镜头 ${(editingShot.order + 1).toString().padStart(2, "0")} · 编辑与返工`}
          close={() => setEditingShot(undefined)}
        >
          <ShotForm
            shot={editingShot}
            assets={assets}
            busy={busy}
            history={() =>
              action(
                async () =>
                  setHistory(
                    await api<unknown[]>(`/versions/${editingShot.id}`),
                  ),
                "已读取历史版本",
              )
            }
            submit={(value) =>
              action(async () => {
                await api(`/shots/${editingShot.id}`, "PUT", value);
                setEditingShot(undefined);
              }, "镜头已保存，重新确认分镜后可生成")
            }
          />
        </Modal>
      )}
      {editingAsset && (
        <Modal
          title={`资产设定 · ${editingAsset.name}`}
          close={() => setEditingAsset(undefined)}
        >
          <AssetForm
            asset={editingAsset}
            busy={busy}
            submit={(value) =>
              action(async () => {
                await api(`/assets/${editingAsset.id}`, "PUT", value);
                setEditingAsset(undefined);
              }, "设定已更新，请重新生成或上传参考图")
            }
          />
        </Modal>
      )}
      {reviewShot && (
        <Modal
          title={`人工审片 · 镜头 ${reviewShot.order + 1}`}
          close={() => setReviewShot(undefined)}
        >
          <ReviewForm
            shot={reviewShot}
            simulation={health?.mode !== "live"}
            busy={busy}
            submit={(value) =>
              action(async () => {
                await api(`/shots/${reviewShot.id}/review`, "POST", value);
                setReviewShot(undefined);
              }, "审片结果已记录")
            }
          />
        </Modal>
      )}
      {history && (
        <Modal title="镜头历史版本" close={() => setHistory(null)}>
          <pre className="dw-history">{JSON.stringify(history, null, 2)}</pre>
          {!history.length && <p>当前为首个版本。</p>}
        </Modal>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
  onClick,
}: {
  label: string;
  value: string;
  sub: string;
  onClick?: () => void;
}) {
  return (
    <button className="dw-stat" onClick={onClick} disabled={!onClick}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{sub}</small>
    </button>
  );
}
function Modal({
  title,
  children,
  close,
}: {
  title: string;
  children: ReactNode;
  close: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
    return () => ref.current?.close();
  }, []);
  return (
    <dialog ref={ref} className="dw-dialog" onCancel={close}>
      <div className="dw-modal-heading">
        <h2>{title}</h2>
        <button
          className="dw-icon"
          title="关闭"
          aria-label="关闭"
          onClick={close}
        >
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
function ProjectForm({
  project,
  busy,
  submit,
}: {
  project?: Project;
  busy: boolean;
  submit: (v: { name: string; budget: number }) => void;
}) {
  const [name, setName] = useState(project?.name || "");
  const [budget, setBudget] = useState(project?.budget || 50);
  return (
    <form
      className="dw-form"
      onSubmit={(e) => {
        e.preventDefault();
        submit({ name, budget });
      }}
    >
      <label>
        项目名称
        <input
          required
          maxLength={80}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="给你的故事起个名字"
        />
      </label>
      <label>
        项目预算上限 / 人民币
        <input
          required
          type="number"
          min="0"
          max="1000000"
          step="0.01"
          value={budget}
          onChange={(e) => setBudget(Number(e.target.value))}
        />
      </label>
      <p className="dw-footnote">
        云任务按配置的单次费用上限预占预算。服务提供方的实际计费需另行核对。模拟模式不产生
        API 费用。
      </p>
      <button className="dw-primary" disabled={busy} type="submit">
        {project ? "保存预算" : "创建项目"} <ArrowRight size={16} />
      </button>
    </form>
  );
}
function EpisodeForm({
  busy,
  submit,
}: {
  busy: boolean;
  submit: (v: {
    title: string;
    style: string;
    script: string;
    target_duration: number;
    aspect: string;
  }) => void;
}) {
  const [title, setTitle] = useState("第一集");
  const [style, setStyle] = useState("both");
  const [script, setScript] = useState("");
  const [duration, setDuration] = useState(75);
  return (
    <form
      className="dw-form"
      onSubmit={(e) => {
        e.preventDefault();
        submit({
          title,
          style,
          script,
          target_duration: duration,
          aspect: "9:16",
        });
      }}
    >
      <div className="dw-form-row">
        <label>
          剧集名称
          <input
            required
            maxLength={100}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>
        <label>
          视觉风格
          <select value={style} onChange={(e) => setStyle(e.target.value)}>
            <option value="both">两种风格分别制作</option>
            <option value="comic">动态漫</option>
            <option value="realistic">写实短剧</option>
          </select>
        </label>
      </div>
      <label>
        目标时长 / 秒
        <input
          type="number"
          min="60"
          max="90"
          required
          value={duration}
          onChange={(e) => setDuration(Number(e.target.value))}
        />
      </label>
      <label>
        已有剧本
        <textarea
          required
          rows={12}
          maxLength={50000}
          value={script}
          onChange={(e) => setScript(e.target.value)}
          placeholder={
            "【场景：旧书店，傍晚】\n林夏：你把那封信藏了三年？\n顾言：我一直在等你。\n动作：林夏翻开旧书。"
          }
        />
      </label>
      <label className="dw-file-field">
        <Upload size={16} /> 从 TXT / Markdown 导入
        <input
          type="file"
          accept=".txt,.md"
          onChange={async (e) => {
            const file = e.target.files?.[0];
            if (file) setScript(await file.text());
          }}
        />
      </label>
      <p className="dw-footnote">
        模拟拆解器按「角色：对白」与「【场景：地点】」识别。云模式使用 ViMax
        规划，结果仍需审阅。
      </p>
      <button className="dw-primary" disabled={busy}>
        导入剧本 <ArrowRight size={16} />
      </button>
    </form>
  );
}
function ShotForm({
  shot,
  assets,
  busy,
  submit,
  history,
}: {
  shot: Shot;
  assets: Asset[];
  busy: boolean;
  submit: (v: unknown) => void;
  history: () => void;
}) {
  const [form, setForm] = useState({ ...shot });
  function change(key: string, value: unknown) {
    setForm((old) => ({ ...old, [key]: value }));
  }
  return (
    <form
      className="dw-form"
      onSubmit={(e) => {
        e.preventDefault();
        const {
          version,
          visual,
          dialogue,
          speaker_id,
          asset_ids,
          duration,
          framing,
          sample,
        } = form;
        submit({
          version,
          visual,
          dialogue,
          speaker_id,
          asset_ids,
          duration,
          framing,
          sample,
        });
      }}
    >
      <label>
        画面与动作
        <textarea
          required
          rows={4}
          value={form.visual}
          onChange={(e) => change("visual", e.target.value)}
        />
      </label>
      <div className="dw-form-row">
        <label>
          镜头类型
          <select
            value={form.framing}
            onChange={(e) => change("framing", e.target.value)}
          >
            {Object.entries(FRAMING).map(([key, name]) => (
              <option key={key} value={key}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label>
          计划时长 / 秒
          <input
            required
            type="number"
            min="1"
            max="30"
            step="0.1"
            value={form.duration}
            onChange={(e) => change("duration", Number(e.target.value))}
          />
        </label>
      </div>
      <label>
        对白
        <textarea
          rows={3}
          maxLength={1000}
          value={form.dialogue}
          onChange={(e) => change("dialogue", e.target.value)}
        />
      </label>
      <label>
        说话人
        <select
          value={form.speaker_id || ""}
          onChange={(e) => change("speaker_id", e.target.value || null)}
        >
          <option value="">无说话人</option>
          {assets
            .filter((a) => a.kind === "character")
            .map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
        </select>
      </label>
      <fieldset>
        <legend>参考资产（角色 / 场景）</legend>
        {assets.map((a) => (
          <label className="dw-check" key={a.id}>
            <input
              type="checkbox"
              checked={form.asset_ids.includes(a.id)}
              onChange={(e) =>
                change(
                  "asset_ids",
                  e.target.checked
                    ? [...form.asset_ids, a.id]
                    : form.asset_ids.filter((id) => id !== a.id),
                )
              }
            />
            {a.name}
          </label>
        ))}
      </fieldset>
      <label className="dw-check">
        <input
          type="checkbox"
          checked={form.sample}
          onChange={(e) => change("sample", e.target.checked)}
        />{" "}
        作为样镜验证
      </label>
      <p className="dw-footnote">
        保存会建立新版本并清空此镜头的当前产物引用；历史素材仍保留。分镜需重新确认，其他镜头成片可复用。
      </p>
      <div className="dw-actions">
        <button className="dw-primary" disabled={busy}>
          保存并标记重做
        </button>
        <button type="button" className="dw-secondary" onClick={history}>
          查看历史版本
        </button>
      </div>
    </form>
  );
}
function AssetForm({
  asset,
  busy,
  submit,
}: {
  asset: Asset;
  busy: boolean;
  submit: (v: unknown) => void;
}) {
  const [form, setForm] = useState(asset);
  return (
    <form
      className="dw-form"
      onSubmit={(e) => {
        e.preventDefault();
        const { version, name, description, costume, voice } = form;
        submit({ version, name, description, costume, voice });
      }}
    >
      {[
        ["name", "名称"],
        ["description", "身份与外观"],
        ["costume", "服装与道具"],
        ["voice", "固定音色 ID"],
      ].map(([key, name]) => (
        <label key={key}>
          {name}
          {key === "description" ? (
            <textarea
              required
              rows={5}
              value={form.description}
              onChange={(e) =>
                setForm({ ...form, description: e.target.value })
              }
            />
          ) : (
            <input
              required={
                key === "name" ||
                (key === "voice" && asset.kind === "character")
              }
              value={String(form[key as keyof Asset] || "")}
              onChange={(e) => setForm({ ...form, [key]: e.target.value })}
            />
          )}
        </label>
      ))}
      <p className="dw-footnote">
        修改设定会使参考图及依赖镜头过期。跨集复用同一资产的镜头也会更新。
      </p>
      <button className="dw-primary" disabled={busy}>
        保存设定
      </button>
    </form>
  );
}
function ReviewForm({
  shot,
  simulation,
  busy,
  submit,
}: {
  shot: Shot;
  simulation: boolean;
  busy: boolean;
  submit: (v: unknown) => void;
}) {
  const [checks, setChecks] = useState(
    Object.fromEntries(CHECKS.map(([key]) => [key, false])),
  );
  const [note, setNote] = useState("");
  return (
    <form
      className="dw-form"
      onSubmit={(e) => {
        e.preventDefault();
        submit({ ...checks, note });
      }}
    >
      <video
        className="dw-review-video"
        controls
        src={media((shot.outputs.lipsync || shot.outputs.video)?.path)}
      />
      {simulation && (
        <p className="dw-notice">
          此为占位视频。勾选仅模拟审阅操作，不能证明真实声音或口型合格。
        </p>
      )}
      <p>{shot.dialogue || "无对白镜头：声音与口型项可按不适用确认。"}</p>
      {CHECKS.map(([key, title]) => (
        <label className="dw-check" key={key}>
          <input
            type="checkbox"
            checked={checks[key]}
            onChange={(e) => setChecks({ ...checks, [key]: e.target.checked })}
          />
          {title}：已通过{simulation ? "（流程模拟）" : ""}
        </label>
      ))}
      <label>
        问题与备注
        <textarea
          rows={3}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="未勾选项将保留为未通过，不能进入成片合成"
        />
      </label>
      <button className="dw-primary" disabled={busy}>
        保存审片结果
      </button>
    </form>
  );
}
function Settings({
  health,
  busy,
  submit,
}: {
  health?: Health;
  busy: boolean;
  submit: (v: string) => void;
}) {
  const [text, setText] = useState(
    JSON.stringify(
      Object.keys(health?.config || {}).length
        ? health?.config
        : {
            vimax_config: "configs/drama.local.yaml",
            image_model: "fal-ai/nano-banana",
            image_edit_model: "fal-ai/nano-banana/edit",
            video_model: "bytedance/seedance-2.0/fast/image-to-video",
            voice_model: "cosyvoice-v3-plus",
            cosyvoice_endpoint: "",
            lipsync_models: {
              realistic: "fal-ai/latentsync",
              comic: "fal-ai/latentsync",
            },
            cost_ceiling_cny: {},
          },
      null,
      2,
    ),
  );
  return (
    <form
      className="dw-form"
      onSubmit={(e) => {
        e.preventDefault();
        submit(text);
      }}
    >
      <div className="dw-config-status">
        <span>
          {health?.mode === "live" ? "云模式已启用" : "当前为模拟模式"}
        </span>
        <span>ViMax 依赖 {health?.vimax_available ? "已安装" : "未安装"}</span>
        <span>fal {health?.fal_configured ? "已配置" : "未配置"}</span>
        <span>配音 {health?.voice_configured ? "已配置" : "未配置"}</span>
      </div>
      <p className="dw-footnote">
        配置不会自动启用付费生成。云模式需在启动服务前设置
        DRAMA_ENABLE_LIVE=1、FAL_KEY、DASHSCOPE_API_KEY。密钥不填写在此页面。单次费用上限使用人民币，由实际所选模型的最高规格费用确定。
      </p>
      <label>
        服务配置 JSON
        <textarea
          className="dw-code-editor"
          rows={17}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </label>
      <p className="dw-footnote">
        动态漫与写实的口型模型分别配置；需各自通过样镜验证。更换配置会暂停使用旧配置的任务。
      </p>
      <button className="dw-primary" disabled={busy}>
        保存服务配置
      </button>
    </form>
  );
}
function Reconcile({
  job,
  busy,
  action,
}: {
  job: Job;
  busy: boolean;
  action: (f: () => Promise<unknown>, m?: string) => Promise<void>;
}) {
  const [id, setId] = useState("");
  return (
    <div className="dw-reconcile">
      <input
        aria-label="服务端任务 ID"
        placeholder="fal 服务端任务 ID"
        value={id}
        onChange={(e) => setId(e.target.value)}
      />
      <button
        className="dw-text-button"
        disabled={busy || !id.trim()}
        onClick={() =>
          action(
            () => api(`/jobs/${job.id}/reconcile`, "POST", { request_id: id }),
            "已恢复查询原任务",
          )
        }
      >
        恢复查询
      </button>
    </div>
  );
}

function NewAssetForm({
  style,
  busy,
  submit,
}: {
  style: Style;
  busy: boolean;
  submit: (value: unknown) => void;
}) {
  const [kind, setKind] = useState("prop");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  return (
    <form
      className="dw-form"
      onSubmit={(e) => {
        e.preventDefault();
        submit({
          style,
          kind,
          name,
          description,
          costume: "",
          voice: "longxiaochun",
        });
      }}
    >
      <label>
        资产类型
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="prop">道具</option>
          <option value="character">角色</option>
          <option value="scene">场景</option>
        </select>
      </label>
      <label>
        资产名称
        <input
          required
          value={name}
          maxLength={100}
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <label>
        身份、外观与细节
        <textarea
          required
          rows={5}
          maxLength={5000}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </label>
      <p className="dw-footnote">
        资产属于当前项目的{STYLE[style]}
        风格。创建后在分镜里绑定，再生成或上传参考图。
      </p>
      <button className="dw-primary" disabled={busy}>
        创建资产
      </button>
    </form>
  );
}

function CostReconcile({
  job,
  busy,
  action,
}: {
  job: Job;
  busy: boolean;
  action: (f: () => Promise<unknown>, m?: string) => Promise<void>;
}) {
  const [amount, setAmount] = useState("");
  if (!["succeeded", "failed", "obsolete"].includes(job.status))
    return <>待核对</>;
  return (
    <form
      className="dw-cost-reconcile"
      onSubmit={(e) => {
        e.preventDefault();
        action(
          () =>
            api(`/jobs/${job.id}/cost`, "PATCH", {
              actual_cost: Number(amount),
            }),
          "实际账单已记录",
        );
      }}
    >
      <input
        aria-label="实际费用（人民币）"
        type="number"
        min="0"
        step="0.0001"
        required
        value={amount}
        placeholder="实际 ¥"
        onChange={(e) => setAmount(e.target.value)}
      />
      <button className="dw-text-button" disabled={busy || !amount}>
        记账
      </button>
    </form>
  );
}
