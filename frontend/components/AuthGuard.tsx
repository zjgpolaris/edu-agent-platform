"use client";
import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { loadAuth } from "@/lib/auth";

const PUBLIC_PATHS = ["/", "/register"];

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setReady(true);
    const auth = loadAuth();
    if (!PUBLIC_PATHS.includes(pathname) && !auth) {
      router.replace("/");
      return;
    }
    if (pathname === "/" && auth) {
      router.replace(auth.role === "teacher" ? "/teacher" : "/student");
    }
  }, [pathname, router]);

  if (!ready && !PUBLIC_PATHS.includes(pathname)) return null;
  return <>{children}</>;
}
