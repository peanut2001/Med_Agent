import { useState, type CSSProperties, type FormEvent } from "react";
import {
  AlertCircle,
  ArrowRight,
  Check,
  Eye,
  EyeOff,
  Fingerprint,
  HeartPulse,
  ImageIcon,
  Loader2,
  Lock,
  MessageSquareText,
  Mic,
  ServerCog,
  ShieldCheck,
  User
} from "lucide-react";
import authBg from "../assets/auth-bg.webp";

type AuthMode = "login" | "register";

type AuthScreenProps = {
  onSubmit: (mode: AuthMode, username: string, password: string) => Promise<void>;
  /** 启动时连不上服务的说明，表单自身的报错优先级更高。 */
  notice?: string | null;
};

// 与后端 agents/local_auth.py 的校验规则保持一致，避免前端放行后端拒绝。
const USERNAME_PATTERN = /^[A-Za-z0-9_.-]{3,32}$/;
const PASSWORD_MIN = 8;
const PASSWORD_MAX = 128;

const capabilities = [
  { icon: MessageSquareText, title: "智能问答", desc: "专业、准确、可靠" },
  { icon: ImageIcon, title: "影像分析", desc: "AI 辅助诊断支持" },
  { icon: Mic, title: "语音交互", desc: "自然对话，高效便捷" }
];

const trustBadges = [
  { icon: ServerCog, label: "本地账号" },
  { icon: Fingerprint, label: "密码加盐哈希" },
  { icon: ShieldCheck, label: "会话隔离" }
];

/** 背景底图（原图直转 WebP，未裁剪未加工）。图里只有插画，文字全部由 DOM 渲染。 */
const authBgVars = { "--auth-bg-image": `url(${authBg})` } as CSSProperties;

/** 登录状态检查期间的过渡页，与登录页共用同一张底图，避免闪烁跳变。 */
export function AuthSplash() {
  return (
    <main className="auth-screen auth-screen--splash" style={authBgVars}>
      <div className="auth-backdrop" aria-hidden="true" />
      <div className="auth-splash">
        <span className="auth-splash__ring" aria-hidden="true">
          <HeartPulse size={22} />
        </span>
        <strong>正在校验会话凭证</strong>
        <small>请稍候，正在连接多智能体医疗助手…</small>
      </div>
    </main>
  );
}

export function AuthScreen({ onSubmit, notice }: AuthScreenProps) {
  const [mode, setMode] = useState<AuthMode>("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const registering = mode === "register";
  const trimmedUsername = username.trim();
  const usernameValid = USERNAME_PATTERN.test(trimmedUsername);
  const passwordValid = password.length >= PASSWORD_MIN && password.length <= PASSWORD_MAX;
  const canSubmit = busy
    ? false
    : registering
      ? usernameValid && passwordValid
      : Boolean(trimmedUsername) && Boolean(password);

  function switchMode(next: AuthMode) {
    if (next === mode) return;
    setMode(next);
    setError(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;

    setBusy(true);
    setError(null);
    try {
      await onSubmit(mode, trimmedUsername, password);
      setPassword("");
    } catch (submitError) {
      const fallback = registering ? "注册失败，请检查输入后重试。" : "登录失败，请检查用户名和密码。";
      setError(submitError instanceof Error ? submitError.message : fallback);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-screen" style={authBgVars}>
      <div className="auth-backdrop" aria-hidden="true" />

      <header className="auth-topbar">
        <div className="auth-logo">
          <span className="auth-logo__mark" aria-hidden="true">
            <HeartPulse size={18} strokeWidth={2.2} />
          </span>
          多智能体医疗助手
        </div>
        <p className="auth-topbar__tagline">
          <span aria-hidden="true" />
          用 AI 守护每一个生命的可能
        </p>
      </header>

      <div className="auth-stage">
        <section className="auth-hero">
          <h1 className="auth-hero__title">
            多智能体<em>医疗</em>助手
          </h1>
          <p className="auth-hero__subtitle">让专业医疗知识触手可及</p>
          <span className="auth-hero__rule" aria-hidden="true" />

          <h2 className="auth-hero__lead">智能问答 / 影像分析 / 语音交互</h2>
          <p className="auth-hero__desc">
            融合多智能体协作能力，
            <br />
            为医生、患者和医疗机构提供更高效、更普惠的智能医疗服务。
          </p>

          <ul className="auth-caps">
            {capabilities.map(({ icon: Icon, title, desc }) => (
              <li key={title}>
                <span className="auth-caps__icon" aria-hidden="true">
                  <Icon size={20} />
                </span>
                <strong>{title}</strong>
                <small>{desc}</small>
              </li>
            ))}
          </ul>

          <p className="auth-hero__sign">
            <strong>AI × 医疗 × 多智能体</strong>
            更智能的医疗助手 · 更美好的健康未来
          </p>
        </section>

        <section className="auth-card">
          <div className="auth-card__head">
            <span className="auth-card__mark" aria-hidden="true">
              <HeartPulse size={24} strokeWidth={2.2} />
            </span>
            <h2>多智能体医疗助手</h2>
            <p>智能问答 / 影像分析 / 语音交互</p>
          </div>

          <div className="auth-tabs" role="tablist" aria-label="登录或注册">
            <button
              type="button"
              role="tab"
              aria-selected={!registering}
              className={`auth-tab${registering ? "" : " is-active"}`}
              onClick={() => switchMode("login")}
            >
              账号登录
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={registering}
              className={`auth-tab${registering ? " is-active" : ""}`}
              onClick={() => switchMode("register")}
            >
              注册账号
            </button>
          </div>

          <form className="auth-form" onSubmit={(event) => void handleSubmit(event)}>
            <label className="auth-field">
              <span className="sr-only">用户名</span>
              <User size={18} className="auth-field__icon" aria-hidden="true" />
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="username"
                placeholder="请输入用户名"
                spellCheck={false}
                required
              />
            </label>

            <label className="auth-field">
              <span className="sr-only">密码</span>
              <Lock size={18} className="auth-field__icon" aria-hidden="true" />
              <input
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete={registering ? "new-password" : "current-password"}
                placeholder="请输入密码"
                maxLength={PASSWORD_MAX}
                required
              />
              <button
                type="button"
                className="auth-field__reveal"
                onClick={() => setShowPassword((current) => !current)}
                aria-label={showPassword ? "隐藏密码" : "显示密码"}
              >
                {showPassword ? <EyeOff size={16} aria-hidden="true" /> : <Eye size={16} aria-hidden="true" />}
              </button>
            </label>

            {registering && (
              <ul className="auth-rules" aria-label="账号规则">
                <li className={usernameValid ? "is-met" : ""}>
                  <Check size={12} aria-hidden="true" />
                  用户名 3–32 位，限字母、数字、<code>.</code> <code>_</code> <code>-</code>
                </li>
                <li className={passwordValid ? "is-met" : ""}>
                  <Check size={12} aria-hidden="true" />
                  密码 {PASSWORD_MIN}–{PASSWORD_MAX} 位字符
                </li>
              </ul>
            )}

            {(error || notice) && (
              <div className="auth-error" role="alert">
                <AlertCircle size={16} aria-hidden="true" />
                <span>{error || notice}</span>
              </div>
            )}

            <button type="submit" className="auth-submit" disabled={!canSubmit}>
              {busy ? (
                <>
                  <Loader2 size={18} className="auth-spin" aria-hidden="true" />
                  {registering ? "正在创建账号…" : "正在验证身份…"}
                </>
              ) : (
                <>
                  {registering ? "注册并进入" : "登录"}
                  <ArrowRight size={18} aria-hidden="true" />
                </>
              )}
            </button>
          </form>

          <p className="auth-divider">账号数据保存在本机</p>

          <div className="auth-trust">
            {trustBadges.map(({ icon: Icon, label }) => (
              <span key={label}>
                <Icon size={14} aria-hidden="true" />
                {label}
              </span>
            ))}
          </div>

          <p className="auth-switch">
            {registering ? "已有账号？" : "还没有账号？"}
            <button type="button" onClick={() => switchMode(registering ? "login" : "register")}>
              {registering ? "返回登录" : "立即注册"}
            </button>
          </p>
        </section>
      </div>

      {/* 左下角是插画里的植物，文字压上去看不清，所以页脚整体靠右 */}
      <footer className="auth-footer">
        <span>用 AI 技术推动医疗普惠，让优质医疗资源触达更多人</span>
        <i aria-hidden="true" />
        <small>AI 输出仅供辅助参考，不能替代医生面诊与专业诊断。</small>
      </footer>
    </main>
  );
}
