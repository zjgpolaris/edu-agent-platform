import AppSidebar, { MobileBottomNav } from "@/app/components/AppSidebar";

export default function TeacherLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="app-shell">
      <AppSidebar role="teacher" />
      <main className="app-main">{children}</main>
      <MobileBottomNav role="teacher" />
    </div>
  );
}
