"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * The live output meter.
 *
 * While a call is live this reads the real microphone through the Web Audio API,
 * so the bars move with the merchant's actual voice. With no stream it renders a
 * still, deterministic silhouette rather than faking activity.
 */
export function VoiceWaveform({
  live,
  bars = 56,
  className,
}: {
  live: boolean;
  bars?: number;
  className?: string;
}) {
  const [levels, setLevels] = React.useState<number[]>(() => restingShape(bars));
  const frameRef = React.useRef<number | null>(null);
  const cleanupRef = React.useRef<(() => void) | null>(null);

  React.useEffect(() => {
    if (!live) {
      setLevels(restingShape(bars));
      return;
    }

    let cancelled = false;

    async function listen() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }

        const context = new AudioContext();
        const source = context.createMediaStreamSource(stream);
        const analyser = context.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);

        const data = new Uint8Array(analyser.frequencyBinCount);

        const tick = () => {
          analyser.getByteFrequencyData(data);
          const step = Math.floor(data.length / bars) || 1;
          const next = Array.from({ length: bars }, (_, index) => {
            const value = data[index * step] ?? 0;
            return Math.max(0.08, value / 255);
          });
          setLevels(next);
          frameRef.current = requestAnimationFrame(tick);
        };
        tick();

        cleanupRef.current = () => {
          if (frameRef.current) cancelAnimationFrame(frameRef.current);
          stream.getTracks().forEach((track) => track.stop());
          void context.close();
        };
      } catch {
        // Microphone blocked: fall back to the resting silhouette rather than
        // pretending to show input we do not have.
        if (!cancelled) setLevels(restingShape(bars));
      }
    }

    void listen();

    return () => {
      cancelled = true;
      cleanupRef.current?.();
      cleanupRef.current = null;
    };
  }, [live, bars]);

  return (
    <div className={cn("flex h-24 items-center justify-center gap-[3px]", className)}>
      {levels.map((level, index) => {
        const distance = Math.abs(index - (bars - 1) / 2) / ((bars - 1) / 2);
        return (
          <span
            key={index}
            className={cn(
              "w-[3px] rounded-full transition-[height,opacity] duration-100",
              live ? "bg-primary" : "bg-primary/25",
            )}
            style={{
              height: `${Math.max(6, level * 88)}%`,
              opacity: live ? 1 - distance * 0.35 : 0.55 - distance * 0.25,
            }}
          />
        );
      })}
    </div>
  );
}

/** A calm, symmetric silhouette so the panel never looks broken at rest. */
function restingShape(bars: number): number[] {
  return Array.from({ length: bars }, (_, index) => {
    const t = index / (bars - 1);
    return 0.16 + 0.34 * Math.sin(t * Math.PI) * (0.6 + 0.4 * Math.sin(t * Math.PI * 7));
  });
}

/** A small static waveform used to label a past session in a list. */
export function WaveformThumb({ seed, className }: { seed: string; className?: string }) {
  const bars = React.useMemo(() => {
    let hash = 0;
    for (let i = 0; i < seed.length; i += 1) hash = (hash * 31 + seed.charCodeAt(i)) >>> 0;
    return Array.from({ length: 28 }, (_, index) => {
      hash = (hash * 1103515245 + 12345) >>> 0;
      const t = index / 27;
      const envelope = Math.sin(t * Math.PI);
      return 0.2 + ((hash % 1000) / 1000) * 0.8 * envelope;
    });
  }, [seed]);

  return (
    <div className={cn("flex h-6 items-center gap-[2px]", className)} aria-hidden="true">
      {bars.map((level, index) => (
        <span
          key={index}
          className="w-[2px] rounded-full bg-primary/50"
          style={{ height: `${Math.max(12, level * 100)}%` }}
        />
      ))}
    </div>
  );
}
