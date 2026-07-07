// 旧路由重定向：/student/weakpoints → /student/review?tab=weakpoints
import { redirect } from "next/navigation";

export default function WeakpointsRedirect() {
  redirect("/student/review?tab=weakpoints");
}
