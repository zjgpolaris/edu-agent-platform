// 旧路由重定向：/student/textbook → /student/materials?tab=textbook
import { redirect } from "next/navigation";

export default function TextbookRedirect() {
  redirect("/student/materials?tab=textbook");
}
