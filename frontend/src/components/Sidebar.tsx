import {
  Activity,
  Brain,
  Database,
  FileSearch,
  HeartPulse,
  Image,
  MessageSquareText,
  Mic,
  ShieldCheck,
  Stethoscope,
  UserCheck
} from "lucide-react";

type SidebarProps = {
  onClear: () => void;
};

export function Sidebar({ onClear }: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="brand-row">
        <div className="brand-mark" aria-hidden="true">
          <HeartPulse size={24} />
        </div>
        <div>
          <span className="eyebrow">Clinical AI Workspace</span>
          <h1>海豚医疗智能助手</h1>
          <p>多智能体协同的医疗问答、检索与影像辅助分析工作台。</p>
        </div>
      </div>

      <section className="sidebar-section">
        <h2>智能体链路</h2>
        <ul className="feature-list">
          <li>
            <MessageSquareText size={18} />
            <span>医疗对话智能体处理症状咨询与健康问答。</span>
          </li>
          <li>
            <Database size={18} />
            <span>RAG 检索智能体整合文档、表格与图像摘要。</span>
          </li>
          <li>
            <FileSearch size={18} />
            <span>置信度不足时交接网络搜索补充公开信息。</span>
          </li>
        </ul>
      </section>

      <section className="sidebar-section sidebar-section--accent">
        <h2>影像分析</h2>
        <div className="capability-grid">
          <span>
            <Brain size={16} />
            脑肿瘤检测
          </span>
          <span>
            <Activity size={16} />
            胸部 X 光分类
          </span>
          <span>
            <Image size={16} />
            皮肤病变分割
          </span>
        </div>
      </section>

      <section className="sidebar-section">
        <h2>工作流保障</h2>
        <ul className="feature-list">
          <li>
            <ShieldCheck size={18} />
            <span>输入输出护栏减少误导性医学建议。</span>
          </li>
          <li>
            <UserCheck size={18} />
            <span>关键影像输出支持人工确认和复核。</span>
          </li>
          <li>
            <Mic size={18} />
            <span>语音转写和文字转语音适配临床沟通。</span>
          </li>
        </ul>
      </section>

      <div className="sidebar-footer">
        <div className="system-pill">
          <Stethoscope size={16} />
          <span>PNG / JPG / JPEG</span>
        </div>
        <button type="button" className="clear-button" onClick={onClear} aria-label="清空对话">
          清空对话
        </button>
      </div>
    </aside>
  );
}
