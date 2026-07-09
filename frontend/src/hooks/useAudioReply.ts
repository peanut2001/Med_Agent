import { useEffect, useRef, useState } from "react";
import { generateSpeech } from "../api/client";

type AudioState = "idle" | "loading" | "playing" | "paused" | "ended" | "error";

export function useAudioReply(text: string) {
  const [state, setState] = useState<AudioState>("idle");
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const objectUrlRef = useRef<string | null>(null);

  function releaseAudio() {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }

    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
  }

  async function togglePlayback() {
    const cleanText = text.trim();
    if (!cleanText) {
      return;
    }

    if (audioRef.current && state === "playing") {
      audioRef.current.pause();
      setState("paused");
      return;
    }

    if (audioRef.current && (state === "paused" || state === "ended")) {
      if (state === "ended") {
        audioRef.current.currentTime = 0;
      }
      await audioRef.current.play();
      setState("playing");
      return;
    }

    setState("loading");
    releaseAudio();

    try {
      const speechText = cleanText.length > 1000 ? `${cleanText.slice(0, 1000)}...` : cleanText;
      const blob = await generateSpeech(speechText);
      const objectUrl = URL.createObjectURL(blob);
      const audio = new Audio(objectUrl);

      objectUrlRef.current = objectUrl;
      audioRef.current = audio;
      audio.onended = () => setState("ended");
      audio.onerror = () => setState("error");

      await audio.play();
      setState("playing");
    } catch (error) {
      console.error("TTS Error:", error);
      releaseAudio();
      setState("error");
    }
  }

  useEffect(() => releaseAudio, []);

  return {
    state,
    togglePlayback
  };
}
