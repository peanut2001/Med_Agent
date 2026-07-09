import { useRef, useState } from "react";
import { transcribeAudio } from "../api/client";

type RecorderState = "idle" | "recording" | "transcribing" | "error";

type UseSpeechRecorderOptions = {
  onTranscript: (transcript: string) => void;
  onError?: (message: string) => void;
};

export function useSpeechRecorder({ onTranscript, onError }: UseSpeechRecorderOptions) {
  const [state, setState] = useState<RecorderState>("idle");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  async function startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream, { mimeType: "audio/webm" });

      chunksRef.current = [];
      recorderRef.current = recorder;

      recorder.addEventListener("dataavailable", (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      });

      recorder.addEventListener("stop", async () => {
        setState("transcribing");
        const audioBlob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        stream.getTracks().forEach((track) => track.stop());

        try {
          const transcript = await transcribeAudio(audioBlob);
          onTranscript(transcript);
          setState("idle");
        } catch (error) {
          console.error("Transcription error:", error);
          onError?.(error instanceof Error ? error.message : "语音转写失败，请重试。");
          setState("error");
          window.setTimeout(() => setState("idle"), 2600);
        }
      });

      recorder.start();
      setState("recording");
    } catch (error) {
      console.error("Error accessing microphone:", error);
      onError?.("无法访问麦克风，请检查浏览器权限设置。");
      setState("error");
      window.setTimeout(() => setState("idle"), 2600);
    }
  }

  function stopRecording() {
    if (recorderRef.current && recorderRef.current.state !== "inactive") {
      recorderRef.current.stop();
    }
  }

  function toggleRecording() {
    if (state === "recording") {
      stopRecording();
      return;
    }

    if (state === "idle" || state === "error") {
      void startRecording();
    }
  }

  return {
    state,
    toggleRecording
  };
}
