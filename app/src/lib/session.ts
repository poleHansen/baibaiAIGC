export type SessionInfo = {
  id: string;
  email: string;
  role: string;
  platformMode: boolean;
  usageToday: { runs: number; chars: number };
  quota: { runs: number; chars: number };
};

const runtimeMode = (import.meta.env.VITE_APP_RUNTIME ?? "desktop").toLowerCase();

export async function loadSession(): Promise<SessionInfo | null> {
  // 桌面端和独立部署没有 /api/me，直接跳过，不产生无意义的请求。
  if (runtimeMode !== "web") {
    return null;
  }
  try {
    const response = await fetch("/api/me");
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as SessionInfo;
  } catch {
    return null;
  }
}

let redirectingToLogin = false;

export function redirectToLogin(): void {
  if (typeof window === "undefined" || redirectingToLogin || window.location.pathname === "/login") {
    return;
  }
  redirectingToLogin = true;
  const next = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  window.location.replace(`/login?next=${encodeURIComponent(next)}`);
}
