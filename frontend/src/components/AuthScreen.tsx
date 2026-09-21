import { useState, type FormEvent } from "react";
import {
  Activity,
  AlertCircle,
  ArrowRight,
  Check,
  Eye,
  EyeOff,
  Fingerprint,
  HeartPulse,
  Loader2,
  Lock,
  LogIn,
  ServerCog,
  ShieldCheck,
  User,
  UserPlus
} from "lucide-react";

type AuthMode = "login" | "register";

type AuthScreenProps = {
  onSubmit: (mode: AuthMode, username: string, password: string) => Promise<void>;
};

// 与后端 agents/local_auth.py 的校验规则保持一致，避免前端放行后端拒绝。
const USERNAME_PATTERN = /^[A-Za-z0-9_.-]{3,32}$/;
const PASSWORD_MIN = 8;
const PASSWORD_MAX = 128;

// 一个完整心电周期（宽 300，首尾回到基线）：基线 → P 波 → QRS 波群 → T 波 → 基线。
const ECG_CYCLE = "h40 l15,0 c5,-12 13,-12 18,0 h15 l7,0 l7,18 l10,-88 l12,120 l8,-50 h18 c10,-24 26,-24 36,0 h114";
const ECG_PATH = `M0,100 ${Array.from({ length: 4 }, () => ECG_CYCLE).join(" ")}`;

const trustBadges = [
  { icon: ServerCog, label: "本地账号" },
  { icon: Fingerprint, label: "密码加盐哈希" },
  { icon: ShieldCheck, label: "会话隔离" }
];

/** 纯 CSS + SVG 绘制的背景：光晕、网格、心电波、暗角，零外部资源请求。 */
function AuthBackdrop() {
  return (
    <div className="auth-backdrop" aria-hidden="true">
      <div className="auth-backdrop__glow auth-backdrop__glow--teal" />
      <div className="auth-backdrop__glow auth-backdrop__glow--cyan" />
      <div className="auth-backdrop__grid" />
      <svg className="auth-backdrop__ecg" viewBox="0 0 1200 200" preserveAspectRatio="none">
        <path className="auth-backdrop__ecg-trail" d={ECG_PATH} />
        <path className="auth-backdrop__ecg-pulse" d={ECG_PATH} />
      </svg>
      <div className="auth-backdrop__vignette" />
    </div>
  );
}

function AuthBrand({ subtitle }: { subtitle: string }) {
  return (
    <div className="auth-brand">
      <div className="auth-brand__mark" aria-hidden="true">
        <HeartPulse size={26} strokeWidth={2.2} />
      </div>
      <div className="auth-brand__copy">
        <span className="auth-brand__eyebrow">DOLPHIN CLINICAL AI</span>
        <h1>海豚医疗智能助手</h1>
        <p>{subtitle}</p>
      </div>
    </div>
  );
}

/** 登录状态检查期间的过渡页，与登录页共用同一套背景，避免闪烁跳变。 */
export function AuthSplash() {
  return (
    <main className="auth-screen">
      <AuthBackdrop />
      <div className="auth-splash">
        <span className="auth-splash__ring" aria-hidden="true">
          <Activity size={22} />
        </span>
        <strong>正在校验会话凭证</strong>
        <small>请稍候，正在连接医疗智能体控制台…</small>
      </div>
    </main>
  );
}

export function AuthScreen({ onSubmit }: AuthScreenProps) {
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
    <main className="auth-screen">
      <AuthBackdrop />

      <section className="auth-card">
        <div className="auth-card__status">
          <span className="auth-card__pulse" aria-hidden="true" />
          控制台在线
        </div>

        <AuthBrand subtitle={registering ? "创建本地测试账号，注册后自动登录。" : "请登录以进入多智能体医疗控制台。"} />

        <div className="auth-tabs" role="tablist" aria-label="登录或注册">
          <button
            type="button"
            role="tab"
            aria-selected={!registering}
            className={`auth-tab${registering ? "" : " is-active"}`}
            onClick={() => switchMode("login")}
          >
            <LogIn size={16} aria-hidden="true" />
            登录
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={registering}
            className={`auth-tab${registering ? " is-active" : ""}`}
            onClick={() => switchMode("register")}
          >
            <UserPlus size={16} aria-hidden="true" />
            注册
          </button>
        </div>

        <form className="auth-form" onSubmit={(event) => void handleSubmit(event)}>
          <label className="auth-field">
            <span className="auth-field__label">用户名</span>
            <span className="auth-field__control">
              <User size={17} className="auth-field__icon" aria-hidden="true" />
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="username"
                placeholder="请输入用户名"
                spellCheck={false}
                required
              />
            </span>
          </label>

          <label className="auth-field">
            <span className="auth-field__label">密码</span>
            <span className="auth-field__control">
              <Lock size={17} className="auth-field__icon" aria-hidden="true" />
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
            </span>
          </label>

          {registering && (
            <ul className="auth-rules" aria-label="账号规则">
              <li className={usernameValid ? "is-met" : ""}>
                <Check size={13} aria-hidden="true" />
                用户名 3–32 位，限字母、数字、<code>.</code> <code>_</code> <code>-</code>
              </li>
              <li className={passwordValid ? "is-met" : ""}>
                <Check size={13} aria-hidden="true" />
                密码 {PASSWORD_MIN}–{PASSWORD_MAX} 位字符
              </li>
            </ul>
          )}

          {error && (
            <div className="auth-error" role="alert">
              <AlertCircle size={16} aria-hidden="true" />
              <span>{error}</span>
            </div>
          )}

          <button type="submit" className="auth-submit" disabled={!canSubmit}>
            {busy ? (
              <>
                <Loader2 size={17} className="auth-spin" aria-hidden="true" />
                {registering ? "正在创建账号…" : "正在验证身份…"}
              </>
            ) : (
              <>
                {registering ? "注册并进入控制台" : "进入控制台"}
                <ArrowRight size={17} aria-hidden="true" />
              </>
            )}
          </button>
        </form>

        <div className="auth-trust">
          {trustBadges.map(({ icon: Icon, label }) => (
            <span key={label}>
              <Icon size={14} aria-hidden="true" />
              {label}
            </span>
          ))}
        </div>

        <p className="auth-disclaimer">
          AI 输出仅供辅助参考，不能替代医生面诊与专业诊断。
        </p>
      </section>
    </main>
  );
}
