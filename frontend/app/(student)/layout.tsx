import AppSidebar, { MobileBottomNav } from "@/app/components/AppSidebar";

export default function StudentLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="app-shell">
      <AppSidebar role="student" />
      <main className="app-main">{children}</main>
      <MobileBottomNav role="student" />
    </div>
  );
}
