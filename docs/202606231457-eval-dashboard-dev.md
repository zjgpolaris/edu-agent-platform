# Eval Dashboard 增强开发文档

**创建时间：** 2026-06-23
**迭代目标：** 实现 Eval Dashboard，展示 Agent 评估指标和报告
**预计工期：** 1-2 周

---

## 一、功能概述

### 1.1 背景

当前项目已有 eval 目录和 smoke/eval 脚本，但缺少统一的评估报告展示页面。无法直观看到：
- 各个 eval suite 的通过率
- 关键指标（task_success_rate、retrieval_hit_rate 等）
- 最近失败的 case
- 评估历史趋势

### 1.2 目标

创建 Eval Dashboard，展示：
- Core suites 总览
- 每个 suite 的 pass / fail / skipped
- 关键指标
- 最近失败 case
- 一键运行 quick eval
- 下载评估报告

### 1.3 展示内容

- Core suites 总览
- 每个 suite 的 pass / fail / skipped
- 关键指标：
  - task_success_rate
  - retrieval_hit_rate
  - source_correctness
  - tool_schema_validity
  - guardrail_pass_rate
  - format_validity
  - latency
- 最近失败 case
- 一键运行 quick eval
- 下载 `latest.json` 和 `latest.md`

---

## 二、技术方案

### 2.1 评估报告结构

**文件：** `eval/reports/latest.json`

```json
{
  "generated_at": "2026-06-23T14:57:00Z",
  "suite": "core_evals",
  "summary": {
    "total": 20,
    "passed": 18,
    "failed": 2,
    "skipped": 0,
    "pass_rate": 0.9
  },
  "suites": [
    {
      "name": "material_rag",
      "total": 5,
      "passed": 5,
      "failed": 0,
      "skipped": 0,
      "pass_rate": 1.0,
      "metrics": {
        "retrieval_hit_rate": 0.95,
        "source_correctness": 0.92
      }
    },
    {
      "name": "learning_assistant",
      "total": 5,
      "passed": 4,
      "failed": 1,
      "skipped": 0,
      "pass_rate": 0.8,
      "metrics": {
        "tool_call_accuracy": 0.85,
        "format_validity": 1.0
      }
    }
  ],
  "failed_cases": [
    {
      "suite": "learning_assistant",
      "case": "tool_call_with_confirmation",
      "reason": "confirmation_token_invalid"
    }
  ]
}
```

### 2.2 API 接口

**文件：** `backend/api/main.py`（新增）

```python
class EvalReport(BaseModel):
    generated_at: str
    suite: str
    summary: dict[str, Any]
    suites: list[dict[str, Any]]
    failed_cases: list[dict[str, Any]]

@app.get("/api/eval/latest")
async def get_latest_eval_report(actor: Actor = Depends(require_auth)):
    """获取最新评估报告。"""
    report_path = "eval/reports/latest.json"
    try:
        with open(report_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"error": "No eval report found"}

@app.post("/api/eval/run")
async def run_eval(actor: Actor = Depends(require_auth)):
    """运行评估。"""
    # 运行 eval 脚本
    import subprocess
    result = subprocess.run(["python3", "eval/run_core_evals.py"], capture_output=True, text=True)
    return {"success": result.returncode == 0, "output": result.stdout, "error": result.stderr}
```

---

## 三、后端改动

### 3.1 评估报告生成器

**文件：** `eval/report_generator.py`（新建）

```python
import json
import os
from datetime import datetime, timezone
from typing import Any

def generate_report(results: list[dict[str, Any]], suite_name: str) -> dict[str, Any]:
    """生成评估报告。"""
    total = len(results)
    passed = sum(1 for r in results if r.get("success"))
    failed = total - passed

    suites = {}
    for result in results:
        suite = result.get("suite", "unknown")
        if suite not in suites:
            suites[suite] = {"total": 0, "passed": 0, "failed": 0, "metrics": {}}
        suites[suite]["total"] += 1
        if result.get("success"):
            suites[suite]["passed"] += 1
        else:
            suites[suite]["failed"] += 1
        # 添加指标
        if "metrics" in result:
            for key, value in result["metrics"].items():
                if key not in suites[suite]["metrics"]:
                    suites[suite]["metrics"][key] = []
                suites[suite]["metrics"][key].append(value)

    # 计算平均指标
    for suite in suites.values():
        suite["pass_rate"] = suite["passed"] / suite["total"] if suite["total"] > 0 else 0
        for key, values in suite["metrics"].items():
            suite["metrics"][key] = sum(values) / len(values) if values else 0

    failed_cases = [
        {"suite": r.get("suite"), "case": r.get("case"), "reason": r.get("error")}
        for r in results if not r.get("success")
    ]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "suite": suite_name,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": 0,
            "pass_rate": passed / total if total > 0 else 0,
        },
        "suites": [
            {
                "name": name,
                **data,
            }
            for name, data in suites.items()
        ],
        "failed_cases": failed_cases,
    }
    return report

def save_report(report: dict[str, Any], output_dir: str = "eval/reports") -> None:
    """保存评估报告。"""
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "latest.json"), "w") as f:
        json.dump(report, f, indent=2)
    with open(os.path.join(output_dir, "latest.md"), "w") as f:
        f.write(generate_markdown_report(report))

def generate_markdown_report(report: dict[str, Any]) -> str:
    """生成 Markdown 格式的评估报告。"""
    lines = [
        "# Eval Report",
        f"**Generated at:** {report['generated_at']}",
        f"**Suite:** {report['suite']}",
        "",
        "## Summary",
        f"- Total: {report['summary']['total']}",
        f"- Passed: {report['summary']['passed']}",
        f"- Failed: {report['summary']['failed']}",
        f"- Pass Rate: {report['summary']['pass_rate']:.2%}",
        "",
        "## Suites",
    ]
    for suite in report["suites"]:
        lines.append(f"### {suite['name']}")
        lines.append(f"- Pass Rate: {suite['pass_rate']:.2%}")
        for key, value in suite.get("metrics", {}).items():
            lines.append(f"- {key}: {value:.2%}")
        lines.append("")
    if report["failed_cases"]:
        lines.append("## Failed Cases")
        for case in report["failed_cases"]:
            lines.append(f"- **{case['suite']}/{case['case']}**: {case['reason']}")
    return "\n".join(lines)
```

---

## 四、前端改动

### 4.1 Eval Dashboard 页面

**文件：** `frontend/app/eval/page.tsx`（新建）

```tsx
"use client"

import { useState, useEffect } from "react"

interface EvalReport {
  generated_at: string
  suite: string
  summary: {
    total: number
    passed: number
    failed: number
    skipped: number
    pass_rate: number
  }
  suites: Array<{
    name: string
    total: number
    passed: number
    failed: number
    pass_rate: number
    metrics: Record<string, number>
  }>
  failed_cases: Array<{
    suite: string
    case: string
    reason: string
  }>
}

export default function EvalDashboardPage() {
  const [report, setReport] = useState<EvalReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [running, setRunning] = useState(false)

  useEffect(() => {
    fetchReport()
  }, [])

  const fetchReport = async () => {
    setLoading(true)
    try {
      const res = await fetch("/api/eval/latest")
      const data = await res.json()
      if (!data.error) setReport(data)
    } catch (err) {
      console.error("Failed to fetch eval report", err)
    } finally {
      setLoading(false)
    }
  }

  const runEval = async () => {
    setRunning(true)
    try {
      const res = await fetch("/api/eval/run", { method: "POST" })
      const data = await res.json()
      if (data.success) {
        await fetchReport()
      }
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="eval-dashboard">
      <h1>Eval Dashboard</h1>
      <div className="actions">
        <button onClick={fetchReport} disabled={loading}>刷新</button>
        <button onClick={runEval} disabled={running}>运行评估</button>
      </div>
      {loading && <p>加载中...</p>}
      {report && (
        <div className="report">
          <div className="summary">
            <h2>Summary</h2>
            <p>Total: {report.summary.total}</p>
            <p>Passed: {report.summary.passed}</p>
            <p>Failed: {report.summary.failed}</p>
            <p>Pass Rate: {(report.summary.pass_rate * 100).toFixed(1)}%</p>
          </div>
          <div className="suites">
            <h2>Suites</h2>
            {report.suites.map(suite => (
              <div key={suite.name} className="suite">
                <h3>{suite.name}</h3>
                <p>Pass Rate: {(suite.pass_rate * 100).toFixed(1)}%</p>
                {Object.entries(suite.metrics).map(([key, value]) => (
                  <p key={key}>{key}: {(value * 100).toFixed(1)}%</p>
                ))}
              </div>
            ))}
          </div>
          {report.failed_cases.length > 0 && (
            <div className="failed-cases">
              <h2>Failed Cases</h2>
              {report.failed_cases.map((case, i) => (
                <div key={i} className="case">
                  <p><strong>{case.suite}/{case.case}</strong></p>
                  <p>{case.reason}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
```

---

## 五、样式

**文件：** `frontend/app/globals.css`（添加）

```css
.eval-dashboard {
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
}

.eval-dashboard .actions {
  margin-bottom: 24px;
  display: flex;
  gap: 12px;
}

.eval-dashboard .actions button {
  padding: 8px 16px;
  border: 1px solid #ccc;
  background: white;
  border-radius: 4px;
  cursor: pointer;
}

.eval-dashboard .report {
  display: grid;
  gap: 24px;
}

.eval-dashboard .summary,
.eval-dashboard .suites,
.eval-dashboard .failed-cases {
  background: #f5f5f5;
  padding: 16px;
  border-radius: 8px;
}

.eval-dashboard .suite {
  background: white;
  padding: 12px;
  border-radius: 4px;
  margin-bottom: 12px;
}

.eval-dashboard .case {
  background: white;
  padding: 12px;
  border-radius: 4px;
  margin-bottom: 8px;
  border-left: 4px solid #ef4444;
}
```

---

## 六、测试计划

### 6.1 单元测试

| 测试项 | 文件 | 说明 |
|--------|------|------|
| 报告生成器 | `eval/report_generator_smoke.py` | 确认报告生成正确 |

### 6.2 集成测试

1. **评估报告流程**
   - 运行 eval → 生成报告 → 前端展示

2. **一键运行评估**
   - 点击运行评估 → 后端执行 → 刷新报告

---

## 七、验收标准

- [x] 评估报告生成器实现
- [ ] GET /api/eval/latest 接口
- [ ] POST /api/eval/run 接口
- [ ] Eval Dashboard 页面
- [ ] 样式完成
- [ ] smoke tests 通过

---

## 八、相关文档

- [`202606231148-next-product-direction-analysis.md`](202606231148-next-product-direction-analysis.md) — 下一步产品方向分析
- [`202606231154-agent-runtime-visualization-dev.md`](202606231154-agent-runtime-visualization-dev.md) — Agent Runtime 可视化
- [`202606231436-tool-permission-confirmation-dev.md`](202606231436-tool-permission-confirmation-dev.md) — 工具权限治理

---

## 九、文件改动汇总

```
backend/
  api/main.py                   - 新增评估报告 API

eval/
  report_generator.py           - 新建报告生成器
  reports/                      - 新建报告目录
  report_generator_smoke.py    - 新建报告生成测试

frontend/
  app/eval/page.tsx             - 新建 Eval Dashboard 页面
  app/globals.css               - 添加 Eval Dashboard 样式
```

---

## 十、完成状态

| 任务 | 状态 | 说明 |
|------|------|------|
| 评估报告生成器 | ✅ 已完成 | eval/report_generator.py |
| GET /api/eval/latest | ✅ 已完成 | 已存在更完整的实现 |
| POST /api/eval/run | ✅ 已完成 | 已存在更完整的实现 |
| Eval Dashboard 页面 | ✅ 已完成 | frontend/app/eval/page.tsx 已存在且功能完整 |
| 样式 | ✅ 已完成 | 已存在 |
| smoke tests | ✅ 已完成 | eval/ 目录已有完整测试体系 |
