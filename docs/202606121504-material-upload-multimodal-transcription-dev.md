# 资料上传多模态教材转写接入开发文档

## 背景

当前「资料上传学习」已完成 Level 1 MVP，并对 Tesseract OCR 做了图片预处理、教材页分区、质量评分、噪声过滤和历史实体纠错。但从教材截图验证结果看，复杂图文混排页面仍存在明显问题：

- 图片说明区被识别成英文乱码。
- 材料研读框中混入非中文噪声。
- 人名、书名、年份、政治纲领等关键事实仍可能错识别。
- Tesseract 对人物照片、书影、材料框、正文混排的教材页达到上限。

用户已确认阿里云百炼全模态模型额度可用，截图中可见 `qwen3.5-omni-*` 系列模型已开启。因此下一步应接入多模态模型，将复杂教材图片从「传统 OCR」升级为「视觉理解转写 + OCR 兜底 + 用户校对」。

## 目标

### 产品目标

1. 对教材截图、扫描页、课堂照片提供更可靠的内容转写。
2. 在现有资料上传流程中新增「多模态转写」识别方式。
3. 保留人工校对流程，避免模型幻觉直接进入学习内容生成。
4. 对失败、超时、额度不足等情况自动 fallback 到现有 Tesseract OCR。
5. 继续遵守 Level 1 约束：不落盘、不入库、不写 Chroma。

### 技术目标

1. 扩展现有 LLM 调用封装，使 DashScope/Bailian OpenAI-compatible 模式支持图片消息。
2. 新增多模态图片转写服务，调用 `qwen3.5-omni-flash` 或 `qwen3.5-omni-plus`。
3. Parse API 支持 `ocr_mode=multimodal`。
4. 多模态输出转换为现有 `MaterialParseResponse`：`text`、`regions`、`quality`、`warnings`。
5. 前端支持选择「多模态转写（推荐）」并展示其结果和风险提示。

## 非目标

本阶段不做：

- 图片文件持久化。
- 上传资料入库。
- 多模态聊天或实时音视频能力。
- 完整教材页匹配系统。
- 自动把多模态结果写入知识库。

## 模型选择

### 推荐默认模型

```text
qwen3.5-omni-flash
```

原因：

- 速度更适合作为上传解析接口。
- 成本和额度消耗更低。
- 对教材页转写应明显优于 Tesseract。

### 高质量可选模型

```text
qwen3.5-omni-plus
```

用途：

- 后续可作为「高质量识别」开关。
- 适合复杂扫描件、低清照片或人工触发重试。

### 环境变量建议

```bash
LLM_PROVIDER=bailian
BAILIAN_API_KEY=<your-bailian-or-dashscope-key>
BAILIAN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_MULTIMODAL=qwen3.5-omni-flash
LLM_MODEL_MULTIMODAL_QUALITY=qwen3.5-omni-plus
```

保留已有文本模型配置：

```bash
LLM_MODEL_FAST=...
LLM_MODEL_QUALITY=...
LLM_MODEL_FALLBACK=...
```

## 当前相关代码

### 后端

- `backend/zode_client.js`
  - 当前支持 Anthropic-compatible 和 OpenAI-compatible 文本聊天。
  - OpenAI-compatible 分支走 `/chat/completions`。
  - 当前 `messages` 主要是纯文本字符串，还未明确支持图片 content block。

- `backend/llm_config.py`
  - `ZodeChatModel` 负责调用 `zode_client.js`。
  - `_build_payload(...)` 当前会把 message content 原样放入 payload，但 Anthropic 分支对内容格式较保守。
  - 可新增专用多模态模型类或复用 `ZodeChatModel` 并确保 OpenAI-compatible payload 支持数组 content。

- `backend/materials/service.py`
  - 当前图片解析入口：`parse_image(...)`。
  - 当前 OCR 模式：`auto | page | textbook`。
  - 已有质量评分、分区、纠错和 warning 机制。

- `backend/materials/schema.py`
  - 当前 `OcrMode` 需要扩展。
  - 当前 response 可复用：`quality`、`regions`、`corrections`、`warnings`。

- `backend/api/main.py`
  - `POST /api/materials/parse` 接收 `ocr_mode`、`preprocess`。

### 前端

- `frontend/app/material-upload/page.tsx`
  - 当前 OCR 模式选项：教材页优化、普通整页、自动。
  - 需要新增「多模态转写（推荐）」。

- `frontend/app/globals.css`
  - 已有 `.material-*` 样式，可扩展推荐标识。

## 总体方案

新增 `ocr_mode=multimodal`：

```text
图片上传
  → 如果 ocr_mode=multimodal 或 auto 判定为复杂教材页
      → 调用 qwen3.5-omni 图片转写
      → 解析结构化 JSON
      → 生成 labeled text + regions + quality + warnings
      → 如果失败，fallback 到现有 Tesseract textbook OCR
  → 用户校对
  → 生成学习内容
```

推荐默认前端模式改为：

```text
multimodal
```

## 后端实施方案

### 1. 扩展 schema

修改 `backend/materials/schema.py`：

```python
OcrMode = Literal["auto", "page", "textbook", "multimodal"]
```

无需新增 response model，复用：

- `OcrQuality`
- `OcrRegion`
- `OcrCorrection`
- `MaterialParseResponse`

多模态 response 约定：

- `quality.level` 通常为 `medium` 或 `high`。
- `quality.needs_review=True`，因为模型转写仍需用户确认。
- `ocr_mode="multimodal"`。
- `regions` 来自模型结构化输出。
- `corrections` 通常为空，除非再经过已有后处理。

### 2. 扩展 zode_client.js 支持图片 content

文件：`backend/zode_client.js`

OpenAI-compatible 的 `/chat/completions` 支持 messages content 为数组：

```json
{
  "role": "user",
  "content": [
    { "type": "text", "text": "请转写图片..." },
    {
      "type": "image_url",
      "image_url": {
        "url": "data:image/png;base64,..."
      }
    }
  ]
}
```

当前 `buildOpenAICompatibleRequest()` 已经基本原样传 `input.messages`，理论上不需要大量改造。但要确认：

- `llm_config.py` 不把数组 content 转成字符串。
- `sanitize_messages(...)` tracing 不因图片 base64 过大爆日志。
- Anthropic fallback 不应接收 OpenAI image content，避免格式不兼容。

建议新增能力开关：

```javascript
function hasImageContent(messages) { ... }
```

如果包含图片消息：

- 只允许 provider 为 `bailian` 或 `dashscope`。
- 不走 Anthropic fallback。
- 错误提示明确：`Multimodal image input requires LLM_PROVIDER=bailian or dashscope`。

### 3. 扩展 llm_config.py

文件：`backend/llm_config.py`

新增模型配置：

```python
MODEL_MULTIMODAL = os.getenv("LLM_MODEL_MULTIMODAL", "qwen3.5-omni-flash")
MODEL_MULTIMODAL_QUALITY = os.getenv("LLM_MODEL_MULTIMODAL_QUALITY", "qwen3.5-omni-plus")

llm_multimodal = ZodeChatModel(
    MODEL_MULTIMODAL,
    max_tokens=4096,
    fallback_models=[],
    name="llm_multimodal",
)

llm_multimodal_quality = ZodeChatModel(
    MODEL_MULTIMODAL_QUALITY,
    max_tokens=4096,
    fallback_models=[MODEL_MULTIMODAL],
    name="llm_multimodal_quality",
)
```

重要：

- 多模态模型不建议 fallback 到文本模型。
- 如果 `LLM_PROVIDER` 不是 `bailian/dashscope`，调用时抛出清晰错误。

可在 `ZodeChatModel` 增加参数：

```python
allow_cross_provider_fallback: bool = True
```

多模态实例设为 `False`，避免 `_provider_model_chain()` 自动追加 Anthropic fallback。

### 4. 新增多模态转写 prompt

文件：可放在 `backend/materials/service.py`，也可拆 `backend/materials/prompts.py`。

建议 prompt：

```text
你是中文历史教材图片转写助手。请严格根据图片内容转写，不要补充图片中不存在的信息。

任务：
1. 按教材阅读顺序转写页面内容。
2. 尽量保留人名、年份、书名、引文、问题和政治纲领原文。
3. 不要描述图片本身的视觉风格，只转写与学习有关的文字。
4. 如果某处看不清，用「[不确定：...]」标记，不要猜测。
5. 输出严格 JSON，不要 Markdown 代码块。

JSON 格式：
{
  "title": "页面主题或空字符串",
  "regions": [
    {
      "name": "caption | main_text | study_box | bottom_text | other",
      "label": "图片说明 | 正文 | 材料研读 | 正文 | 其他",
      "text": "转写文本",
      "uncertain": false
    }
  ],
  "warnings": ["不确定或看不清的提示"]
}
```

### 5. 新增图片编码 helper

文件：`backend/materials/service.py`

```python
def image_data_url(content_type: str, data: bytes) -> str:
    mime = content_type if content_type in {"image/png", "image/jpeg", "image/jpg"} else "image/png"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
```

注意：

- 不写临时文件。
- 对过大图片可先用 Pillow 压缩成 JPEG/PNG 后再发给模型，避免请求过大。
- 仍保留 15MB 上传限制。

### 6. 新增多模态转写函数

文件：`backend/materials/service.py`

```python
def transcribe_image_with_multimodal_model(
    filename: str,
    content_type: str,
    data: bytes,
) -> MaterialParseResponse:
    ...
```

流程：

1. 校验 `LLM_PROVIDER in {"bailian", "dashscope"}`。
2. 构造 data URL。
3. 调用 `llm_multimodal.invoke(messages)`。
4. `parse_json_object(...)` 解析模型输出。
5. 将 regions 转为 `OcrRegion`。
6. 合并 text：

```text
【图片说明】
...

【正文】
...

【材料研读】
...
```

7. 对转写文本复用已有：
   - `postprocess_ocr_text(...)`
   - `score_ocr_text(...)`
8. 返回 `MaterialParseResponse`：
   - `source_type="image"`
   - `ocr_mode="multimodal"`
   - `quality.needs_review=True`
   - warnings 包含：
     - “本次使用多模态模型转写，生成前仍建议人工确认。”
     - 模型 warnings

### 7. parse_image 接入 multimodal fallback

修改 `parse_image(...)`：

```python
if resolved_mode == "multimodal":
    try:
        return transcribe_image_with_multimodal_model(...)
    except Exception as exc:
        warnings.append("多模态转写失败，已回退到教材页 OCR")
        return parse_textbook_image(...)
```

注意当前函数结构可能返回 tuple，需要设计清楚：

- 方案 A：`transcribe_image_with_multimodal_model` 直接返回 `MaterialParseResponse`。
- 方案 B：返回 tuple 后由 `parse_image` 包装。

推荐方案 A，减少分支复杂度。

### 8. auto 模式策略

当前 `auto` 默认走 `textbook`。接入后建议改为：

```python
def resolve_image_mode(mode: OcrMode) -> OcrMode:
    if mode == "auto":
        return "multimodal" if multimodal_configured() else "textbook"
    return mode
```

`multimodal_configured()`：

- `LLM_PROVIDER in {"bailian", "dashscope"}`
- 有 `BAILIAN_API_KEY` 或 `DASHSCOPE_API_KEY`

## 前端实施方案

### 1. 扩展 OCR 模式类型

文件：`frontend/app/material-upload/page.tsx`

```ts
type OcrMode = "auto" | "textbook" | "page" | "multimodal";
```

### 2. 新增模式选项

推荐默认：

```ts
const [ocrMode, setOcrMode] = useState<OcrMode>("multimodal");
```

模式选项：

```ts
{ value: "multimodal", label: "多模态转写", description: "推荐：适合教材截图、图文混排和材料框" }
{ value: "textbook", label: "教材页 OCR", description: "传统 OCR 分区识别" }
{ value: "page", label: "普通整页", description: "适合纯文字图片" }
{ value: "auto", label: "自动", description: "系统选择识别方式" }
```

### 3. UI 文案

当 `parsedMeta.ocr_mode === "multimodal"`：

- meta strip 显示：`多模态转写 · qwen3.5-omni`
- warning：
  - “多模态转写更适合复杂教材页，但仍需校对不确定项。”

### 4. 校对逻辑保持不变

即使多模态质量较高，也继续要求：

```text
我已校对人名、年份、书名和明显乱码
```

原因：多模态模型可能幻觉或补全。

## API 兼容性

### Request

现有 parse request 增加一种模式即可：

```text
POST /api/materials/parse
file=<image>
grade=八年级
subject=历史
ocr_mode=multimodal
preprocess=true
```

`preprocess` 对多模态模式可以忽略，或用于发送前压缩图片。

### Response

保持现有响应结构：

```json
{
  "filename": "xxx.png",
  "content_type": "image/png",
  "source_type": "image",
  "text": "【图片说明】...",
  "pages": [...],
  "warnings": ["本次使用多模态模型转写，生成前仍建议人工确认。"],
  "quality": {
    "level": "medium",
    "needs_review": true
  },
  "regions": [...],
  "corrections": [],
  "ocr_mode": "multimodal"
}
```

## 错误处理

### 多模态未配置

如果用户选择 `multimodal`，但环境未配置 Bailian：

建议行为：

- 后端自动 fallback 到 `textbook` OCR。
- warnings 加：

```text
多模态模型未配置，已回退到传统 OCR。
```

不要直接 500，避免上传流程中断。

### 多模态调用失败

包括：

- API key 错误。
- 额度不足。
- 模型未开通。
- 请求超时。
- 图片过大。

建议行为：

- fallback 到 `textbook` OCR。
- warnings 加：

```text
多模态转写失败，已回退到传统 OCR。请检查模型配置或稍后重试。
```

### JSON 解析失败

模型返回非 JSON：

1. 尝试 `extract_json_text` / `parse_json_object`。
2. 如果仍失败，把模型原文作为一个 `正文` region。
3. warnings 加：

```text
多模态模型未返回结构化 JSON，已保留原始转写文本。
```

## 验证方案

### 1. 环境检查

```bash
export LLM_PROVIDER=bailian
export BAILIAN_API_KEY=<your-key>
export BAILIAN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
export LLM_MODEL_MULTIMODAL=qwen3.5-omni-flash
```

### 2. 后端编译

```bash
PYTHONPATH=backend /Users/cengjiguang/.local/python3.12/bin/python3 -m py_compile \
  backend/llm_config.py \
  backend/materials/schema.py \
  backend/materials/service.py \
  backend/api/main.py
```

### 3. 单独测试 zode_client.js 多模态

可写一个一次性 Python 或 Node 调用，发送：

```json
{
  "model": "qwen3.5-omni-flash",
  "max_tokens": 1024,
  "messages": [
    {
      "role": "user",
      "content": [
        { "type": "text", "text": "请简要转写图片中的中文文字。" },
        { "type": "image_url", "image_url": { "url": "data:image/png;base64,..." } }
      ]
    }
  ]
}
```

预期：返回图片文字说明。

### 4. Parse API 测试

```bash
curl -X POST http://localhost:8000/api/materials/parse \
  -H "Authorization: Bearer <token>" \
  -F "file=@/Users/cengjiguang/Downloads/ScreenShot_2026-06-12_114555_074.png" \
  -F "grade=八年级" \
  -F "subject=历史" \
  -F "ocr_mode=multimodal" \
  -F "preprocess=true"
```

检查：

- 是否返回 `ocr_mode=multimodal`。
- 是否包含 `【材料研读】` 等结构化段落。
- 是否比 Tesseract 少英文乱码。
- 是否仍要求 `needs_review=true`。

### 5. 前端测试

1. 打开 `/material-upload`。
2. 选择「多模态转写（推荐）」。
3. 上传教材截图。
4. 确认：
   - 识别结果更接近原文。
   - 分区结果可读。
   - 前端仍要求校对确认。
5. 校对后生成学习内容。
6. 确认生成卡片结构正常。

## 与现有 OCR 的关系

多模态不是完全替代 Tesseract，而是作为复杂图片的优先路径：

| 输入类型 | 推荐路径 |
|---|---|
| 文本型 PDF | PyMuPDF 直接抽文本 |
| 清晰纯文字图片 | Tesseract page OCR |
| 教材截图/扫描页 | 多模态转写 |
| 多模态失败 | Tesseract textbook OCR fallback |

## 风险与注意事项

### 1. 多模态可能幻觉

模型可能补全文字或改写原文，因此必须：

- Prompt 明确“不猜测，看不清就标不确定”。
- 前端保留校对确认。
- 不直接入库。

### 2. 图片 base64 会增加请求体积

需要：

- 保留上传大小限制。
- 必要时压缩图片。
- 避免把 base64 写入 trace/log。

### 3. tracing 脱敏

`sanitize_messages(...)` 可能记录 message 内容。必须确认或修改：

- 图片 data URL 不进入日志。
- 只保留占位，例如 `[image:data-url omitted]`。

### 4. 模型供应商限制

多模态依赖 Bailian/DashScope，Anthropic-compatible fallback 不一定支持相同 image payload。多模态调用必须限制 provider 或提供清晰 fallback。

## 推荐实施顺序

### Milestone A：多模态调用通路

1. 扩展 `llm_config.py` 增加 `llm_multimodal`。
2. 确认 `zode_client.js` OpenAI-compatible 可传 image content。
3. 增加 tracing 脱敏保护。
4. 用本地一次性脚本验证 qwen3.5-omni 能读图。

### Milestone B：接入 materials parse

1. `OcrMode` 增加 `multimodal`。
2. `parse_image(...)` 支持 `multimodal`。
3. 新增 `transcribe_image_with_multimodal_model(...)`。
4. 失败 fallback 到 `textbook` OCR。

### Milestone C：前端入口与验证

1. 前端模式增加「多模态转写（推荐）」。
2. 默认模式改为 `multimodal`。
3. 展示多模态 warning 和校对确认。
4. 用教材截图端到端验证。

## 最终建议

建议优先实现 **qwen3.5-omni-flash 多模态转写 + Tesseract fallback**。

这样既能显著改善复杂教材截图的识别质量，又不会丢掉当前已实现的 OCR 兜底能力。对于教育场景，最终产品表达应是：

> 系统先用多模态模型或 OCR 生成资料草稿，用户确认后再生成学习内容；任何图片识别结果都不直接作为事实入库。
