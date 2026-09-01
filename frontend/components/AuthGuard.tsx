"use client";
import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { homeForRole, loadAuth } from "@/lib/auth";

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
    const explicitRoleSwitch = pathname === "/" && new URLSearchParams(window.location.search).has("role");
    if (pathname === "/" && auth && !explicitRoleSwitch) {
      router.replace(homeForRole(auth.role));
    }
  }, [pathname, router]);

  if (!ready && !PUBLIC_PATHS.includes(pathname)) return null;
  return <>{children}</>;
}
