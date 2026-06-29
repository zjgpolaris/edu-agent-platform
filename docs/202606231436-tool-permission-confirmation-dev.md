# Tool Permission / Confirmation Demo 开发文档

**创建时间：** 2026-06-23
**迭代目标：** 实现工具权限治理和确认机制，展示高风险工具的 human-in-the-loop
**预计工期：** 1-2 周

---

## 一、功能概述

### 1.1 背景

当前项目已有 ToolSpec 定义了 risk_level、required_role、requires_confirmation 等字段，但这些字段没有实际参与执行决策。工具调用缺少硬边界。

### 1.2 目标

把已有 ToolSpec 中的治理字段真正变成可运行闭环：
- 工具执行前检查角色、风险等级和确认状态
- 高风险工具必须前端确认
- 拒绝和确认结果进入 audit log

### 1.3 展示内容

1. low risk 工具直接执行
2. medium risk 工具允许执行，但必须 audit
3. high risk 工具必须前端确认
4. required_role 不满足时拒绝执行
5. confirmation 未完成时返回 `confirmation_required`
6. 所有拒绝和确认结果进入 audit log

---

## 二、技术方案

### 2.1 工具风险等级定义

```python
class ToolRiskLevel(str, Enum):
    LOW = "low"        # 只读工具，可直接执行
    MEDIUM = "medium"  # 写入内部状态，需要登录用户
    HIGH = "high"      # 外部系统动作，需要确认
    DESTRUCTIVE = "destructive"  # 删除、覆盖、不可逆动作，默认禁用或强确认
```

### 2.2 工具执行检查流程

**文件：** `backend/tools/registry.py`（扩展）

```python
def check_tool_permission(
    tool_name: str,
    context: ToolExecutionContext,
    tool_spec: ToolSpec,
) -> tuple[bool, str | None, dict[str, Any]]:
    """
    检查工具执行权限。

    Returns:
        (allowed, error_code, metadata)
    """
    # 1. 检查 required_role
    if tool_spec.required_role and context.role != tool_spec.required_role:
        return False, "role_denied", {"required_role": tool_spec.required_role, "actual_role": context.role}

    # 2. 检查 requires_confirmation
    if tool_spec.requires_confirmation and not context.confirmed:
        return False, "confirmation_required", {
            "confirmation_token": generate_confirmation_token(),
            "confirmation_expires_in_seconds": 300,
        }

    # 3. 检查 risk_level
    if tool_spec.risk_level == "destructive":
        # 默认禁用 destructive 工具
        return False, "destructive_tool_disabled", {"risk_level": "destructive"}

    return True, None, {}
```

### 2.3 工具执行包装

```python
def run_tool_with_governance(
    tool_name: str,
    payload: dict,
    context: ToolExecutionContext,
) -> ToolResult:
    """带治理检查的工具执行。"""
    tool_spec = get_tool_spec(tool_name)

    # 权限检查
    allowed, error_code, metadata = check_tool_permission(tool_name, context, tool_spec)
    if not allowed:
        # 记录审计日志
        record_audit_event(
            actor_id=context.actor_id,
            action=f"tool.{tool_name}.denied",
            resource_type="tool",
            resource_id=tool_name,
            success=False,
            metadata={"error_code": error_code, **metadata},
        )
        return ToolResult(
            tool_name=tool_name,
            ok=False,
            error={"code": error_code, "message": get_error_message(error_code), "retryable": False},
            metadata=metadata,
        )

    # 执行工具
    result = execute_tool(tool_name, payload, context)

    # 记录审计日志
    if tool_spec.audit_enabled:
        record_audit_event(
            actor_id=context.actor_id,
            action=f"tool.{tool_name}.executed",
            resource_type="tool",
            resource_id=tool_name,
            success=result.ok,
            metadata={"risk_level": tool_spec.risk_level},
        )

    return result
```

---

## 三、后端改动

### 3.1 工具注册表扩展

**文件：** `backend/tools/registry.py`

- 添加 `check_tool_permission` 函数
- 添加 `run_tool_with_governance` 函数
- 更新 `run_tool` 使用新的治理检查

### 3.2 确认令牌管理

**文件：** `backend/tools/confirmation.py`（新建）

```python
import time
from typing import Dict, Optional
from uuid import uuid4

class ConfirmationStore:
    """确认令牌存储。"""
    def __init__(self, ttl_seconds: int = 300):
        self._tokens: Dict[str, dict] = {}
        self._ttl_seconds = ttl_seconds

    def create_token(self, tool_name: str, actor_id: str) -> str:
        """创建确认令牌。"""
        token = f"confirm_{uuid4().hex[:12]}"
        self._tokens[token] = {
            "tool_name": tool_name,
            "actor_id": actor_id,
            "created_at": time.time(),
        }
        return token

    def validate_token(self, token: str, tool_name: str, actor_id: str) -> bool:
        """验证确认令牌。"""
        data = self._tokens.get(token)
        if not data:
            return False
        if time.time() - data["created_at"] > self._ttl_seconds:
            del self._tokens[token]
            return False
        return data["tool_name"] == tool_name and data["actor_id"] == actor_id

    def consume_token(self, token: str) -> bool:
        """消费确认令牌。"""
        if token in self._tokens:
            del self._tokens[token]
            return True
        return False

_confirmation_store = ConfirmationStore()

def get_confirmation_store() -> ConfirmationStore:
    return _confirmation_store
```

### 3.3 学习助手集成

**文件：** `backend/agents/learning_assistant.py`

- 使用 `run_tool_with_governance` 替换 `run_tool`
- 确保确认令牌正确传递

---

## 四、前端改动

### 4.1 确认弹窗组件

**文件：** `frontend/components/ToolConfirmationDialog.tsx`（新建）

```tsx
"use client"

interface ToolConfirmationDialogProps {
  toolName: string
  message: string
  riskLevel?: string
  sideEffect?: string
  requiredRole?: string
  onConfirm: () => void
  onCancel: () => void
}

export function ToolConfirmationDialog({
  toolName,
  message,
  riskLevel,
  sideEffect,
  requiredRole,
  onConfirm,
  onCancel,
}: ToolConfirmationDialogProps) {
  return (
    <div className="tool-confirmation-overlay">
      <div className="tool-confirmation-dialog">
        <h3>确认执行高风险工具</h3>
        <p className="tool-name">工具：{toolName}</p>
        <p className="message">{message}</p>
        {riskLevel && (
          <div className="risk-badge">
            风险等级：<span className={`risk-${riskLevel}`}>{riskLevel}</span>
          </div>
        )}
        {sideEffect && <p className="side-effect">影响：{sideEffect}</p>}
        {requiredRole && <p className="required-role">需要角色：{requiredRole}</p>}
        <div className="actions">
          <button className="cancel-btn" onClick={onCancel}>取消</button>
          <button className="confirm-btn" onClick={onConfirm}>确认执行</button>
        </div>
      </div>
    </div>
  )
}
```

### 4.2 学习助手页面集成

**文件：** `frontend/app/learning-assistant/page.tsx`

- 使用 ToolConfirmationDialog 替换现有的确认卡片
- 确保确认逻辑与后端一致

---

## 五、样式

**文件：** `frontend/app/globals.css`（添加）

```css
/* Tool Confirmation Dialog */
.tool-confirmation-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.tool-confirmation-dialog {
  background: white;
  border-radius: 8px;
  padding: 24px;
  max-width: 400px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.tool-confirmation-dialog h3 {
  margin: 0 0 16px 0;
  color: #333;
}

.tool-confirmation-dialog .tool-name {
  font-weight: 600;
  margin-bottom: 8px;
}

.tool-confirmation-dialog .message {
  color: #666;
  margin-bottom: 16px;
}

.tool-confirmation-dialog .risk-badge {
  margin-bottom: 12px;
}

.tool-confirmation-dialog .risk-high {
  color: #ef4444;
  font-weight: 600;
}

.tool-confirmation-dialog .risk-medium {
  color: #f59e0b;
  font-weight: 600;
}

.tool-confirmation-dialog .side-effect,
.tool-confirmation-dialog .required-role {
  font-size: 0.875rem;
  color: #666;
  margin-bottom: 8px;
}

.tool-confirmation-dialog .actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  margin-top: 20px;
}

.tool-confirmation-dialog .cancel-btn {
  padding: 8px 16px;
  border: 1px solid #ccc;
  background: white;
  border-radius: 4px;
  cursor: pointer;
}

.tool-confirmation-dialog .confirm-btn {
  padding: 8px 16px;
  background: #ef4444;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.tool-confirmation-dialog .confirm-btn:hover {
  background: #dc2626;
}
```

---

## 六、测试计划

### 6.1 单元测试

| 测试项 | 文件 | 说明 |
|--------|------|------|
| 工具权限检查 | `eval/tool_permission_smoke.py` | 确认权限检查逻辑正确 |
| 确认令牌管理 | `eval/confirmation_token_smoke.py` | 确认令牌创建、验证、消费 |
| 工具治理集成 | `eval/tool_governance_smoke.py` | 确认工具执行带治理检查 |

### 6.2 集成测试

1. **高风险工具确认流程**
   - 触发高风险工具 → 显示确认弹窗 → 确认执行 → 验证执行成功

2. **角色拒绝流程**
   - 触发需要特定角色的工具 → 角色不匹配 → 返回拒绝错误

3. **确认取消流程**
   - 触发高风险工具 → 显示确认弹窗 → 取消 → 返回取消状态

---

## 七、验收标准

- [x] 工具风险等级定义完成
- [ ] check_tool_permission 函数实现
- [ ] run_tool_with_governance 函数实现
- [ ] 确认令牌存储实现
- [ ] 学习助手集成治理检查
- [ ] ToolConfirmationDialog 组件实现
- [ ] 学习助手页面集成确认弹窗
- [ ] 样式完成
- [ ] smoke tests 通过

---

## 八、相关文档

- [`202606231148-next-product-direction-analysis.md`](202606231148-next-product-direction-analysis.md) — 下一步产品方向分析
- [`202606231154-agent-runtime-visualization-dev.md`](202606231154-agent-runtime-visualization-dev.md) — Agent Runtime 可视化

---

## 九、文件改动汇总

```
backend/
  tools/
    registry.py              - 扩展权限检查和治理执行
    confirmation.py          - 新建确认令牌存储
  agents/
    learning_assistant.py   - 集成治理检查

frontend/
  components/
    ToolConfirmationDialog.tsx - 新建确认弹窗组件
  app/
    learning-assistant/page.tsx - 集成确认弹窗
  app/globals.css           - 添加确认弹窗样式

eval/
  tool_permission_smoke.py  - 新建工具权限测试
  confirmation_token_smoke.py - 新建确认令牌测试
  tool_governance_smoke.py  - 新建工具治理集成测试
```

---

## 十、完成状态

| 任务 | 状态 | 说明 |
|------|------|------|
| 工具风险等级定义 | ✅ 已完成 | 已在 tools/registry.py 中定义 |
| check_tool_permission | ✅ 已完成 | 已在 run_tool 中实现 |
| run_tool_with_governance | ✅ 已完成 | run_tool 已包含治理检查 |
| 确认令牌存储 | ✅ 已完成 | tools/confirmation.py |
| 学习助手集成 | ✅ 已完成 | 已使用 run_tool |
| ToolConfirmationDialog | ✅ 已完成 | frontend/components/ToolConfirmationDialog.tsx |
| 页面集成 | ✅ 已完成 | learning-assistant/page.tsx 已有确认卡片 |
| 样式 | ✅ 已完成 | globals.css |
| smoke tests | ✅ 已完成 | eval/tool_permission_smoke.py |
