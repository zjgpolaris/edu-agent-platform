import HistoryBreadcrumb from "./Breadcrumb";

export default function HistoryLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <HistoryBreadcrumb />
      {children}
    </>
  );
}
