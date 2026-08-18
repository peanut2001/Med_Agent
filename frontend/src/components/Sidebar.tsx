import {
  BrainCircuit,
  HeartPulse,
  ImagePlus,
  MessageSquareText,
  Mic,
  RotateCcw,
  ShieldCheck,
  Sparkles
} from "lucide-react";

type SidebarProps = {
  onClear: () => void;
  onLogout: () => void;
  currentUser: string;
};

const capabilities = [
  {
    icon: MessageSquareText,
    title: "智能问答",
    description: "症状、用药与健康信息咨询"
  },
  {
    icon: ImagePlus,
    title: "影像分析",
    description: "脑部、胸片与皮肤图像辅助识别"
  },
  {
    icon: Mic,
    title: "语音交互",
    description: "语音转写与回复朗读"
  }
];

export function Sidebar({ onClear, onLogout, currentUser }: SidebarProps) {
  return (
    <aside className="sidebar" aria-label="应用导航">
      <div className="brand-row">
        <div className="brand-mark" aria-hidden="true">
          <HeartPulse size={23} strokeWidth={2.2} />
        </div>
        <div className="brand-copy">
          <span className="eyebrow">Dolphin Clinical AI</span>
          <h1>海豚医疗智能助手</h1>
        </div>
      </div>

      <div className="system-card" aria-label="系统状态">
        <div className="system-card__heading">
          <span className="status-dot" aria-hidden="true" />
          <strong>智能体系统在线</strong>
        </div>
        <p>根据问题类型自动调度医疗问答、检索与影像分析能力。</p>
      </div>

      <nav className="capability-nav" aria-label="核心能力">
        <div className="section-label">核心能力</div>
        <ul>
          {capabilities.map(({ icon: Icon, title, description }) => (
            <li key={title}>
              <span className="capability-icon" aria-hidden="true">
                <Icon size={18} />
              </span>
              <span>
                <strong>{title}</strong>
                <small>{description}</small>
              </span>
            </li>
          ))}
        </ul>
      </nav>

      <div className="sidebar-spacer" />

      <section className="safety-note" aria-label="安全说明">
        <div className="safety-note__icon" aria-hidden="true">
          <ShieldCheck size={18} />
        </div>
        <div>
          <strong>临床安全提示</strong>
          <p>AI 输出仅供辅助参考，不能替代医生面诊与专业诊断。</p>
        </div>
      </section>

      <div className="sidebar-footer">
        <div className="sidebar-user">已登录：{currentUser}</div>
        <div className="sidebar-meta">
          <span><BrainCircuit size={15} /> 多智能体协同</span>
          <span><Sparkles size={15} /> 隐私会话</span>
        </div>
        <button type="button" className="clear-button" onClick={onClear} aria-label="清空当前对话">
          <RotateCcw size={17} aria-hidden="true" />
          <span>清空对话</span>
        </button>
        <button type="button" className="clear-button" onClick={onLogout} aria-label="退出登录">
          <span>退出登录</span>
        </button>
      </div>
    </aside>
  );
}
