/** @type {import('next').NextConfig} */
const nextConfig = {
  // Docker(Render) 部署用精简自包含产物；Vercel 会忽略该字段、走自有构建。
  output: "standalone",
  async redirects() {
    return [
      { source: "/student-home", destination: "/student", permanent: true },
      { source: "/teacher-home", destination: "/teacher", permanent: true },
      { source: "/teacher/dashboard", destination: "/teacher", permanent: true },
      { source: "/history-character", destination: "/student/history/chat", permanent: true },
      { source: "/history-debate", destination: "/student/history/debate", permanent: true },
      { source: "/history-games", destination: "/student/history/games", permanent: true },
      { source: "/history-map", destination: "/student/history/map", permanent: true },
      { source: "/essay-grading", destination: "/teacher/grading?tab=essay", permanent: true },
      { source: "/essay-grade", destination: "/teacher/grading?tab=essay", permanent: true },
      { source: "/essay-dashboard", destination: "/teacher/grading?tab=stats", permanent: true },
      { source: "/homework-grading", destination: "/teacher/grading?tab=homework", permanent: true },
    ];
  },
};

module.exports = nextConfig;
