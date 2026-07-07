"use client";
import { useEffect, useMemo, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { fetchApiJson, normalizeError } from "@/lib/api";

type PreferenceDimension = {
  label: string;
  options: Record<string, string>;
  default: string;
};
type PreferenceSchema = Record<string, PreferenceDimension>;
type Preferences = Record<string, string>;

function defaultsFromSchema(schema: PreferenceSchema | null): Preferences {
  if (!schema) return {};
  return Object.fromEntries(Object.entries(schema).map(([k, v]) => [k, v.default]));
}

export default function StudentSettingsPage() {
  const { user } = useAuth();
  const [schema, setSchema] = useState<PreferenceSchema | null>(null);
  const [prefs, setPrefs] = useState<Preferences>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user?.actorId) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    Promise.all([
      fetchApiJson<PreferenceSchema>("/api/preferences/schema", { token: user.token, fallbackMessage: "偏好配置加载失败" }),
      fetchApiJson<Preferences>(`/api/students/${user.actorId}/preferences`, { token: user.token, fallbackMessage: "偏好设置加载失败" }),
    ]).then(([schemaData, savedPrefs]) => {
      if (cancelled) return;
      setSchema(schemaData);
      setPrefs({ ...defaultsFromSchema(schemaData), ...savedPrefs });
    }).catch((err) => {
      if (!cancelled) setError(normalizeError(err, "偏好配置暂不可用，请稍后重试"));
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [user?.actorId, user?.token]);

  const schemaKeys = useMemo(() => Object.keys(schema || {}), [schema]);

  async function handleSave() {
    if (!user?.actorId || !user?.token || saving || !schema) return;
    setSaving(true);
    setSaved(false);
    try {
      const updated = await fetchApiJson<Preferences>(`/api/students/${user.actorId}/preferences`, {
        method: "PUT",
        token: user.token,
        body: { preferences: prefs },
        fallbackMessage: "保存失败",
      });
      setPrefs({ ...defaultsFromSchema(schema), ...updated });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="pref-loading">加载中…</div>;

  if (error || !schema) return (
    <div className="pref-page">
      <style>{CSS}</style>
      <h1 className="pref-title">学习偏好设置</h1>
      <div className="pref-error">
        <strong>偏好配置暂不可用</strong>
        <p>{error || "请稍后刷新重试。"}</p>
      </div>
    </div>
  );

  return (
    <div className="pref-page">
      <style>{CSS}</style>
      <h1 className="pref-title">学习偏好设置</h1>
      <p className="pref-subtitle">
        配置你的 AI 学伴教学风格，让辅导更贴合你的学习习惯。
      </p>

      {schemaKeys.map((key) => {
        const dim = schema[key];
        return (
          <div key={key} className="pref-group">
            <label className="pref-label">{dim.label}</label>
            <div className="pref-options">
              {Object.entries(dim.options).map(([val, desc]) => (
                <button
                  key={val}
                  type="button"
                  className={`pref-option ${prefs[key] === val ? "active" : ""}`}
                  onClick={() => setPrefs((prev) => ({ ...prev, [key]: val }))}
                >
                  <span className="pref-option-check">{prefs[key] === val ? "●" : "○"}</span>
                  <span className="pref-option-text">{desc}</span>
                </button>
              ))}
            </div>
          </div>
        );
      })}

      <div className="pref-actions">
        <button className="pref-save-btn" onClick={handleSave} disabled={saving}>
          {saving ? "保存中…" : "保存设置"}
        </button>
        {saved && <span className="pref-saved-hint">✓ 已保存</span>}
      </div>

      <div className="pref-notice">
        <strong>💡 提示</strong>
        <p>偏好设置会在下次开始 AI 辅导时生效，不会影响正在进行的课程。</p>
      </div>
    </div>
  );
}

const CSS = `
.pref-loading { padding:40px; text-align:center; color:var(--muted,#7a7068); }
.pref-page { max-width:700px; margin:0 auto; padding:24px 20px 48px; }
.pref-title { font-size:22px; font-weight:700; color:var(--ink,#1a1612); margin:0 0 8px; }
.pref-subtitle { font-size:14px; color:var(--muted,#7a7068); margin:0 0 28px; }
.pref-error { background:#fffaf0; border:1px dashed #e5d2bf; border-radius:12px; padding:16px; margin-top:18px; }
.pref-error strong { display:block; font-size:15px; color:var(--ink,#1a1612); margin-bottom:4px; }
.pref-error p { margin:0; color:var(--muted,#7a7068); font-size:13px; line-height:1.7; }
.pref-group { margin-bottom:24px; }
.pref-label { display:block; font-size:15px; font-weight:600; color:var(--ink,#1a1612); margin-bottom:10px; }
.pref-options { display:flex; flex-direction:column; gap:8px; }
.pref-option { display:flex; align-items:center; gap:10px; background:#fdfbf7; border:1px solid #eee6d8; border-radius:10px; padding:12px 14px; text-align:left; cursor:pointer; transition:border-color .15s, background .15s; }
.pref-option:hover { border-color:var(--cinnabar,#b7422b); }
.pref-option.active { background:#fff8e1; border-color:#f59e0b; }
.pref-option-check { font-size:16px; color:var(--cinnabar,#b7422b); flex-shrink:0; }
.pref-option.active .pref-option-check { color:#f59e0b; }
.pref-option-text { font-size:14px; color:var(--ink,#1a1612); }
.pref-actions { display:flex; align-items:center; gap:12px; margin-top:32px; }
.pref-save-btn { font-size:15px; font-weight:700; color:#fff; background:var(--jade,#2d6a4f); border:none; border-radius:24px; padding:10px 28px; cursor:pointer; transition:background .15s; }
.pref-save-btn:hover:not(:disabled) { background:#235a3f; }
.pref-save-btn:disabled { opacity:.6; cursor:not-allowed; }
.pref-saved-hint { font-size:14px; color:var(--jade,#2d6a4f); }
.pref-notice { background:#f0faf5; border:1px solid #a5d6a7; border-radius:10px; padding:14px 16px; margin-top:24px; }
.pref-notice strong { display:block; font-size:13px; color:var(--jade,#2d6a4f); margin-bottom:4px; }
.pref-notice p { font-size:13px; color:#558b2f; margin:0; }
`;
