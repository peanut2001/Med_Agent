import { Loader2, Pause, Play, RotateCcw, TriangleAlert, Volume2 } from "lucide-react";
import { useAudioReply } from "../hooks/useAudioReply";

type AudioReplyButtonProps = {
  text: string;
};

const buttonCopy = {
  idle: "播放语音回复",
  loading: "生成中...",
  playing: "暂停",
  paused: "继续播放",
  ended: "重新播放",
  error: "语音失败"
};

export function AudioReplyButton({ text }: AudioReplyButtonProps) {
  const { state, togglePlayback } = useAudioReply(text);

  const Icon =
    state === "loading"
      ? Loader2
      : state === "playing"
        ? Pause
        : state === "ended"
          ? RotateCcw
          : state === "error"
            ? TriangleAlert
            : state === "idle"
              ? Volume2
              : Play;

  return (
    <button
      className={`secondary-action audio-action audio-action--${state}`}
      type="button"
      onClick={() => void togglePlayback()}
      disabled={state === "loading"}
      aria-label={buttonCopy[state]}
    >
      <Icon aria-hidden="true" className={state === "loading" ? "spin" : undefined} size={16} />
      <span>{buttonCopy[state]}</span>
    </button>
  );
}
