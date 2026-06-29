"use client";
import { createContext, useContext, useEffect, useState } from "react";
import { AuthUser, loadAuth, saveAuth, clearAuth } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

interface AuthContextValue {
  user: AuthUser | null;
  ready: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (studentId: string, password: string, displayName?: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue>({} as AuthContextValue);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => { setUser(loadAuth()); setReady(true); }, []);

  async function login(username: string, password: string) {
    const res = await fetch(`${API}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) throw new Error("用户名或密码错误");
    const data = await res.json();
    const auth: AuthUser = { actorId: data.actor_id, role: data.role, displayName: data.display_name, token: data.token };
    saveAuth(auth);
    setUser(auth);
  }

  async function register(studentId: string, password: string, displayName?: string) {
    const res = await fetch(`${API}/api/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ student_id: studentId, password, display_name: displayName || null }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || "注册失败");
    const data = await res.json();
    const auth: AuthUser = { actorId: data.actor_id, role: data.role, displayName: displayName || studentId, token: data.token };
    saveAuth(auth);
    setUser(auth);
  }

  function logout() {
    clearAuth();
    setUser(null);
  }

  return <AuthContext.Provider value={{ user, ready, login, register, logout }}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
