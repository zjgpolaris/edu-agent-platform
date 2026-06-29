# 历史时空地图模块开发文档

## 1. 背景与目标

在现有 EduAgent 历史学习能力基础上，新增**时空地图**模块：用户可在中国地图上拖动时间轴，地图随之展示该时间段内的历史事件标注，点击标注可联动已有 AI 角色对话能力，实现"空间+时间+AI 解说"三轴联动的沉浸式历史学习体验。

**参考社区热门实现**：
- [Chronas](https://chronas.org/)：开源历史地图，按年代展示世界/区域事件
- David Rumsey Map Collection 时间轴交互模式
- 国内"中国历史地图集"数字化项目
- Vercel AI SDK + MapLibre 的 AI-driven map narrative 演示

---

## 2. 功能设计

### 2.1 核心交互流程

```
用户进入 /history-map
    │
    ├─ 地图初始化（中国全图，默认朝代：秦）
    │
    ├─ 时间轴滑动 → 筛选该时间段事件 → 地图更新标注
    │
    ├─ 点击事件标注 → 右侧面板展示事件摘要 + 触发 AI 角色对话
    │
    └─ 对话框中 AI 向导可调用 map_actions 控制地图（跳转/高亮/推荐关联事件）
```

### 2.2 时间粒度

| 粒度 | 说明 |
|------|------|
| 朝代级 | 秦、汉、唐、宋、元、明、清等，适合初中年级 |
| 百年级 | BC 300 ~ AD 2000，步进 100 年 |
| 十年级 | 近现代（1840 至今），步进 10 年 |

MVP 阶段仅实现朝代级，其余后续迭代。

### 2.3 事件标注样式

- 图标按事件类型区分：战役 ⚔️、政治 🏛️、文化 📜、自然灾害 🌊
- 标注聚合：同区域多事件 cluster 展示，放大后散开
- 高亮：AI 向导推荐的事件闪烁高亮

---

## 3. 数据设计

### 3.1 地理事件数据结构

现有 `corpus.json` 无坐标信息，新增独立数据文件：

```json
// knowledge_base/history/geo_events.json
[
  {
    "id": "battle_changping",
    "title": "长平之战",
    "year_start": -260,
    "year_end": -260,
    "dynasty": "战国",
    "lat": 35.9,
    "lng": 112.8,
    "location_name": "长平（今山西高平）",
    "type": "battle",
    "summary": "秦赵之间规模最大的野战，赵军大败，白起坑杀降卒四十万。",
    "character": "白起",
    "corpus_refs": ["长平之战", "白起"]
  }
]
```

关键字段：
- `year_start/year_end`：负数为 BC
- `character`：关联现有角色对话的人物名，可为 null
- `corpus_refs`：触发 RAG 检索的关键词

### 3.2 数据来源策略

**初期（MVP）**：人工整理 50-100 条核心事件，覆盖七年级上下册教材重点内容。

**批量标注脚本**（`scripts/annotate_geo_events.py`）：
- 从 `corpus.json` 按 topic 聚合，提取地名
- 调用 LLM 补全 `lat/lng/dynasty/year_start`
- 人工校验后入库

**后续**：接入 [CCCR 中国历史地理数据库](https://chgis.fairbank.fas.harvard.edu/) 或 [历史地图集 API](https://www.historygis.com/)

---

## 4. 技术架构

### 4.1 后端

新增路由 `backend/api/main.py`：

```
GET  /api/history/geo/events
     ?dynasty=战国
     &year_start=-280&year_end=-220   (可选，优先 dynasty)
     &bbox=73,18,135,53              (可选，经纬度边界框)
     → [GeoEvent]

POST /api/history/geo/narrate         (SSE)
     { event_id, user_query?, session_id }
     → SSE: delta | map_actions | fact_card
```

新增 Agent 文件 `backend/agents/history_map_agent.py`：

```
retrieve_geo_context          # 按 corpus_refs 查 RAG
    ↓
generate_narration            # 角色第一人称叙事（复用 history_character 逻辑）
    ↓
generate_map_actions          # 输出结构化地图操作指令
    ↓
SSE emit
```

`map_actions` 结构：

```json
{
  "type": "map_actions",
  "actions": [
    { "action": "highlight", "event_ids": ["battle_guandu"] },
    { "action": "fly_to",    "lat": 35.5, "lng": 114.2, "zoom": 7 },
    { "action": "set_year",  "year": -200 }
  ]
}
```

前端监听此 SSE 事件类型，调用 Leaflet API 执行。

### 4.2 前端

新增页面 `frontend/app/history-map/`：

```
history-map/
  page.tsx              # 服务端壳，加载元数据
  HistoryMapClient.tsx  # 主客户端组件（地图 + 时间轴 + 对话面板）
  MapLayer.tsx          # Leaflet 地图封装
  TimelineSlider.tsx    # 时间轴控件
  EventPanel.tsx        # 右侧事件详情 + AI 对话
```

**地图库选型**：`react-leaflet` + `leaflet` — 与现有项目技术栈（Next.js 14）兼容，无需额外配置，社区生态成熟。

中国地图 GeoJSON：使用开源 [china-geojson](https://github.com/longwosion/geojson-map-china) 数据，省级边界。

### 4.3 AI Agent 能力接入点

| 入口 | 触发方式 | 实现方式 |
|------|----------|----------|
| 事件点击解说 | 点击地图标注 | 调用 `/api/history/geo/narrate`，SSE 流式 |
| 对话驱动导航 | 用户输入"带我看..." | Agent 解析意图 → 返回 `map_actions` |
| 因果链推荐 | 解说结束后 | Agent 输出 `related_events[]`，前端高亮 |
| 朝代概览旁白 | 切换朝代时 | 轻量提示词生成 100 字朝代简介，非 Agent 流程 |

---

## 5. 开发阶段规划

### Milestone 1：静态地图 + 时间轴（3天）

- [ ] `geo_events.json` 初版数据（50条，覆盖七上重点）
- [ ] `/api/history/geo/events` 接口（直接读 JSON，无 DB）
- [ ] `HistoryMapClient.tsx`：Leaflet 地图渲染 + 朝代级时间轴
- [ ] 事件 Marker 聚合展示
- [ ] 右侧面板：事件标题 + 摘要

### Milestone 2：AI 解说接入（2天）

- [ ] `history_map_agent.py`：复用 history_character RAG + 生成逻辑
- [ ] `/api/history/geo/narrate` SSE 接口
- [ ] `EventPanel.tsx` 接入 SSE 流式展示
- [ ] `map_actions` SSE 事件解析 + Leaflet 联动

### Milestone 3：对话驱动导航（2天）

- [ ] `EventPanel.tsx` 增加对话输入框
- [ ] Agent 增加意图识别节点：`navigate_intent` → `map_actions`
- [ ] 因果链推荐：`related_events` 高亮展示

### Milestone 4：数据扩充（持续）

- [ ] `scripts/annotate_geo_events.py` 批量标注脚本
- [ ] 扩充至 200+ 条事件，覆盖七下/八上
- [ ] 百年级时间轴粒度支持

---

## 6. 关键约束与风险

| 风险 | 说明 | 应对 |
|------|------|------|
| 地名坐标准确性 | 古地名与现代坐标对应误差 | MVP 人工校验，标注"大致位置"提示 |
| Leaflet SSR 兼容 | Next.js App Router SSR 下 Leaflet 报错 | `dynamic import` + `ssr: false` |
| 大量标注性能 | 500+ 标注点渲染卡顿 | Leaflet.markercluster 聚合 |
| Agent 幻觉地名 | LLM 生成错误坐标 | 坐标来源仅用 geo_events.json，不让 LLM 生成坐标 |

---

## 7. 相关文件

- `knowledge_base/history/geo_events.json`（待创建）
- `backend/agents/history_map_agent.py`（待创建）
- `backend/api/main.py`（扩展路由）
- `frontend/app/history-map/`（待创建）
- `scripts/annotate_geo_events.py`（待创建）

## 8. 参考

- 现有角色对话 Agent：`backend/agents/history_character.py`
- 现有 SSE 实现：`backend/api/main.py` `/api/history/character/chat/stream`
- react-leaflet 文档：https://react-leaflet.js.org/
- china-geojson：https://github.com/longwosion/geojson-map-china
