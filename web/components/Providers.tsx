"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { api, getToken, wsUrl } from "@/lib/api";
import type { AlertOut, CameraOut, WsMessage } from "@/lib/types";

interface Ctx {
  cameras: CameraOut[];
  camerasError: string | null;
  camerasLoading: boolean;
  refreshCameras: () => Promise<void>;
  alerts: AlertOut[];
  wsConnected: boolean;
  onAlert: (fn: (a: AlertOut, update: boolean) => void) => () => void;
  soundOn: boolean;
  setSoundOn: (v: boolean) => void;
  audioUnlocked: boolean;
  play: (url: string) => Promise<boolean>;
  theme: "dark" | "light";
  setTheme: (t: "dark" | "light") => void;
  toast: (msg: string, kind?: "ok" | "err") => void;
}

const AppCtx = createContext<Ctx | null>(null);

export function useApp(): Ctx {
  const c = useContext(AppCtx);
  if (!c) throw new Error("useApp outside Providers");
  return c;
}

const SILENT_WAV =
  "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA=";

export function Providers({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isLogin = pathname?.startsWith("/login");
  const [ready, setReady] = useState(false);
  const [cameras, setCameras] = useState<CameraOut[]>([]);
  const [camerasError, setCamerasError] = useState<string | null>(null);
  const [camerasLoading, setCamerasLoading] = useState(true);
  const [alerts, setAlerts] = useState<AlertOut[]>([]);
  const [wsConnected, setWsConnected] = useState(false);
  const [soundOn, setSoundOnState] = useState(true);
  const [audioUnlocked, setAudioUnlocked] = useState(false);
  const listeners = useRef(new Set<(a: AlertOut, update: boolean) => void>());
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [theme, setThemeState] = useState<"dark" | "light">("dark");
  const [toasts, setToasts] = useState<{ id: number; msg: string; kind: "ok" | "err" }[]>([]);
  useEffect(() => {
    setThemeState(document.documentElement.dataset.theme === "light" ? "light" : "dark");
  }, []);
  const setTheme = (t: "dark" | "light") => {
    setThemeState(t);
    if (t === "light") document.documentElement.dataset.theme = "light";
    else delete document.documentElement.dataset.theme;
    try {
      localStorage.setItem("nazar_theme", t);
    } catch {
      /* ignore */
    }
  };
  const toast = useCallback((msg: string, kind: "ok" | "err" = "ok") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, msg, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4000);
  }, []);

  // auth gate
  useEffect(() => {
    const t = getToken();
    if (!t && !isLogin) {
      router.replace("/login/");
      return;
    }
    setReady(true);
  }, [isLogin, router]);

  useEffect(() => {
    try {
      setSoundOnState(localStorage.getItem("nazar_sound") !== "off");
    } catch {
      /* ignore */
    }
  }, []);

  const setSoundOn = (v: boolean) => {
    setSoundOnState(v);
    try {
      localStorage.setItem("nazar_sound", v ? "on" : "off");
    } catch {
      /* ignore */
    }
  };

  // browsers block autoplay until a user gesture: unlock on the first tap anywhere
  useEffect(() => {
    if (audioUnlocked) return;
    const unlock = () => {
      const a = audioRef.current ?? new Audio();
      audioRef.current = a;
      a.src = SILENT_WAV;
      a.play().then(() => setAudioUnlocked(true)).catch(() => undefined);
    };
    window.addEventListener("pointerdown", unlock, { once: true });
    window.addEventListener("keydown", unlock, { once: true });
    return () => {
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
    };
  }, [audioUnlocked]);

  const play = useCallback(
    async (url: string) => {
      if (!soundOn) return false;
      const a = audioRef.current ?? new Audio();
      audioRef.current = a;
      a.src = url;
      try {
        await a.play();
        return true;
      } catch {
        return false;
      }
    },
    [soundOn],
  );

  const refreshCameras = useCallback(async () => {
    try {
      setCameras(await api.cameras());
      setCamerasError(null);
    } catch (e) {
      setCamerasError((e as Error).message);
    } finally {
      setCamerasLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!ready || isLogin) return;
    refreshCameras();
    api.alerts().then(setAlerts).catch(() => undefined);
    const id = setInterval(refreshCameras, 15000);
    return () => clearInterval(id);
  }, [ready, isLogin, refreshCameras]);

  // WebSocket: alerts + camera status, with reconnect
  useEffect(() => {
    if (!ready || isLogin) return;
    let ws: WebSocket | null = null;
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let ping: ReturnType<typeof setInterval> | null = null;
    const connect = () => {
      ws = new WebSocket(wsUrl());
      ws.onopen = () => {
        setWsConnected(true);
        ping = setInterval(() => ws?.readyState === 1 && ws.send("ping"), 25000);
      };
      ws.onmessage = (ev) => {
        let m: WsMessage;
        try {
          m = JSON.parse(ev.data);
        } catch {
          return;
        }
        if (m.type === "alert") {
          setAlerts((prev) => [m.alert, ...prev.filter((a) => a.id !== m.alert.id)].slice(0, 100));
          listeners.current.forEach((fn) => fn(m.alert, m.update));
        } else if (m.type === "camera_status") {
          setCameras((prev) =>
            prev.map((c) => {
              const s = m.cameras.find((x) => x.id === c.id);
              return s ? { ...c, ...s } : c;
            }),
          );
        }
      };
      ws.onclose = () => {
        setWsConnected(false);
        if (ping) clearInterval(ping);
        if (!closed) retry = setTimeout(connect, 3000);
      };
    };
    connect();
    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      if (ping) clearInterval(ping);
      ws?.close();
    };
  }, [ready, isLogin]);

  const onAlert = useCallback((fn: (a: AlertOut, update: boolean) => void) => {
    listeners.current.add(fn);
    return () => {
      listeners.current.delete(fn);
    };
  }, []);

  if (!ready && !isLogin) return <div className="min-h-dvh" />;
  return (
    <AppCtx.Provider
      value={{ cameras, camerasError, camerasLoading, refreshCameras, alerts, wsConnected, onAlert, soundOn, setSoundOn, audioUnlocked, play, theme, setTheme, toast }}
    >
      {children}
      <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-20 z-[60] flex flex-col items-center gap-2 px-4 md:bottom-6">
        {toasts.map((t) => (
          <div key={t.id} className={`pointer-events-auto rounded-2xl px-4 py-2.5 text-sm shadow-lg ${t.kind === "err" ? "bg-danger text-white" : "bg-foreground text-background"}`}>{t.msg}</div>
        ))}
      </div>
    </AppCtx.Provider>
  );
}
