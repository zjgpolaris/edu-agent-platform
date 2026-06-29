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
