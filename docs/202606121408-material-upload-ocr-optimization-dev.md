# 资料上传 OCR 与文本提取可靠性优化开发文档

## 背景

当前 Level 1「资料上传学习」已支持上传 PDF、PNG、JPG，并通过 `POST /api/materials/parse` 提取文本，再由用户确认文本后生成摘要、讲解和练习题。

在教材截图测试中，Tesseract 对整页图片的识别质量不稳定，出现了明显错识别：

- 人名错识别：`孙逸仙` → `孙狗仙`，`邹容` 周边出现英文乱码。
- 图片说明和书影标题干扰正文识别。
- 中英文混杂噪声：如 `PERRY`、`Pen bg`、`HELLS CREE`。
- OCR 结果虽然能提取部分正文，但不能直接作为可靠学习材料输入。

因此，图片 OCR 当前只能作为「人工校对草稿」，需要优化提取链路，提升教材截图、扫描页和课堂图片的可用性。

## 目标

### 产品目标

1. 提高教材截图/照片 OCR 的可读性和可用性。
2. 明确区分「可靠文本」和「需校对文本」。
3. 降低错误 OCR 直接进入生成链路导致的知识错误风险。
4. 保持 Level 1 不入库、不写 Chroma、不持久化上传文件的约束。

### 技术目标

1. PDF 文本型资料优先直接抽取文本。
2. 图片资料先做预处理，再 OCR。
3. 针对教材页做基础版面分区，减少图片/页脚/书影对正文的干扰。
4. OCR 后进行轻量清洗、历史实体纠错和噪声提示。
5. 前端展示识别质量提示，引导用户校对关键实体。

## 非目标

本阶段不做：

- 上传资料入库。
- 自动写入知识库或 Chroma。
- 完整文档管理系统。
- 复杂版面分析模型训练。
- 对所有复杂扫描件达到出版级 OCR 精度。

## 当前相关代码

### 后端

- `backend/materials/service.py`
  - `parse_material_bytes(...)`
  - `parse_pdf(...)`
  - `parse_image(...)`
  - `image_to_text(...)`
  - `analyze_material(...)`

- `backend/materials/schema.py`
  - `MaterialParseResponse`
  - `MaterialPage`
  - `MaterialAnalyzeResponse`

- `backend/api/main.py`
  - `POST /api/materials/parse`
  - `POST /api/materials/analyze`

### 前端

- `frontend/app/material-upload/page.tsx`
  - 上传文件
  - 展示 OCR 文本
  - 用户编辑确认
  - 生成学习内容

- `frontend/app/globals.css`
  - `.material-*` 样式

## 优化方案总览

建议分 4 个阶段推进。

| 阶段 | 名称 | 重点 | 预期收益 |
|---|---|---|---|
| Phase 1 | OCR 预处理增强 | 放大、灰度、对比度、锐化、二值化 | 低成本提升中文正文识别 |
| Phase 2 | Tesseract 参数优化 | `chi_sim+eng`、PSM 策略、白名单/黑名单 | 减少串行和混排误读 |
| Phase 3 | 教材版面分区 | 正文、材料框、图片说明、页脚分区 OCR | 显著降低图片干扰 |
| Phase 4 | OCR 后处理与风险提示 | 噪声过滤、实体纠错、低置信提示 | 降低错误内容进入生成 |

## Phase 1：图片预处理增强

### 目标

在调用 Tesseract 前，对图片进行更适合中文教材页的预处理。

### 后端实现位置

`backend/materials/service.py`

新增函数：

```python
def preprocess_image_for_ocr(image: Image.Image) -> Image.Image:
    ...
```

### 处理步骤

建议流程：

1. 转 RGB。
2. 根据图片尺寸自动放大：
   - 宽度小于 1600px 时放大 2 倍。
   - 宽度小于 1000px 时放大 3 倍。
3. 转灰度。
4. 增强对比度。
5. 适度锐化。
6. 对黑字白底教材页做二值化。

### 示例实现方向

```python
from PIL import ImageEnhance, ImageFilter


def preprocess_image_for_ocr(image: Image.Image) -> Image.Image:
    image = image.convert("RGB")
    width, height = image.size
    scale = 1
    if width < 1000:
        scale = 3
    elif width < 1600:
        scale = 2
    if scale > 1:
        image = image.resize((width * scale, height * scale), Image.Resampling.LANCZOS)

    gray = image.convert("L")
    gray = ImageEnhance.Contrast(gray).enhance(1.8)
    gray = gray.filter(ImageFilter.SHARPEN)
    return gray.point(lambda p: 255 if p > 180 else 0)
```

### 注意事项

- 不要覆盖原图文件；只处理内存中的 `Image` 对象。
- 对照片类图片，强二值化可能丢失信息，需要保留 fallback：
  - 先用预处理图 OCR。
  - 如果结果过短，再用原图 OCR。

## Phase 2：Tesseract 参数优化

### 当前问题

整页教材截图包含图片、图注、正文、材料框、页脚，默认 OCR 容易将多个区域串在一起。

### 建议参数

对于整页教材正文：

```text
-l chi_sim+eng --psm 6 --oem 3
```

对于整页混合版面，可尝试：

```text
-l chi_sim+eng --psm 4 --oem 3
```

对于单个材料框或正文块：

```text
-l chi_sim+eng --psm 6 --oem 3
```

### 后端实现

修改 `image_to_text(...)`：

```python
config = "--oem 3 --psm 6"
text = pytesseract.image_to_string(processed_image, lang="chi_sim+eng", config=config)
```

如果结果低质量，可 fallback 到 `--psm 4`。

### 低质量判断

新增函数：

```python
def score_ocr_text(text: str) -> dict:
    ...
```

可用指标：

- 中文字符占比。
- 英文乱码 token 数量。
- 总字符数。
- 非法符号密度。
- 是否包含常见教材关键词，如“材料研读”“为什么”“中国历史”“年级上册”。

示例判定：

- 中文字符少于 30 个：低质量。
- 英文连续乱码 token 超过 5 个：需要校对。
- `?`, `|`, `_`, 随机大写英文比例过高：需要校对。

## Phase 3：教材版面分区 OCR

### 目标

不要对整张教材截图直接 OCR，而是切分为若干区域分别 OCR，再按阅读顺序合并。

### MVP 分区策略

先实现基于比例的轻量分区，不引入 OpenCV 复杂依赖。

对于竖版教材页图片，可粗分为：

1. 上部图片/图注区：0%–38%
2. 中部正文/材料框区：35%–68%
3. 下部正文区：65%–95%
4. 页脚：95%–100%，默认忽略或单独低权重识别

但这张示例页的主要学习文本集中在：

- 图片说明区：人物与书名。
- 正文区：孙中山成为革命党领袖。
- 材料研读框。
- 下方中国同盟会正文。

建议第一版分区：

```python
def split_textbook_regions(image: Image.Image) -> list[OcrRegion]:
    return [
        OcrRegion("caption", crop top/mid caption area),
        OcrRegion("main_text", crop middle-left正文),
        OcrRegion("study_box", crop pink material box),
        OcrRegion("bottom_text", crop lower正文),
    ]
```

### 更稳妥的实现方式

如果不做自动检测，先提供两种 OCR 模式：

- `page`：整页识别。
- `textbook`：教材页分区识别。

前端可以默认传：

```text
ocr_mode=textbook
```

后端 `POST /api/materials/parse` 增加可选表单字段：

```python
ocr_mode: str | None = Form("auto")
```

### 合并格式

返回文本时带区域标签，便于用户校对：

```text
【图片说明】
邹容（1885—1905）和《革命军》
陈天华（1875—1905）和《猛回头》《警世钟》

【正文】
在长期的革命斗争中……

【材料研读】
孙逸仙者……
为什么孙中山能成为革命党公认的领袖？

【正文】
为了集中革命力量……
```

这样即使 OCR 不完美，用户也更容易知道哪里需要修正。

## Phase 4：OCR 后处理与实体纠错

### 目标

对 OCR 草稿进行轻量清洗，不让明显噪声影响生成。

### 后端实现位置

`backend/materials/service.py`

新增：

```python
def clean_ocr_noise(text: str) -> tuple[str, list[str]]:
    ...


def correct_history_entities(text: str) -> tuple[str, list[str]]:
    ...
```

### 噪声清理规则

可先移除或标记：

- 单独成行的乱码英文：`PERRY`, `Pen bg`, `Leip pried Pee`, `HELLS CREE`。
- 过多竖线：`||`, `|`。
- 无意义短行：长度小于 2 且不是中文/数字。
- 页脚水印或浏览器截图残留。

### 历史实体词表

第一版可内置一个小词表，后续再从 `textbooks/structured` 或知识库抽取。

示例：

```python
HISTORY_ENTITY_CORRECTIONS = {
    "孙狗仙": "孙逸仙",
    "孙狗山": "孙中山",
    "和孙逸仙": "孙逸仙",
    "邹答": "邹容",
    "邹客": "邹容",
    "陈天华": "陈天华",
    "同盈会": "同盟会",
    "中国同盈会": "中国同盟会",
    "光复含": "光复会",
    "兴中含": "兴中会",
    "华兴含": "华兴会",
    "民 报": "民报",
    "猛回头": "猛回头",
    "警世钟": "警世钟",
}
```

### 年份和标点修复

规则：

- `1875一1905` → `1875—1905`
- `1885—1905 )` → `1885—1905）`
- 连续空格压缩。
- 中文段落中英文括号统一。

### 风险提示

返回 `warnings`：

- “图片 OCR 结果已做自动纠错，请重点校对人名、年份和书名。”
- “检测到疑似 OCR 乱码，已过滤部分低置信文本。”
- “材料来自图片识别，生成前建议人工确认。”

## API 调整建议

### `POST /api/materials/parse`

当前请求：

```text
multipart/form-data
file
optional grade
optional subject
```

建议增加：

```text
ocr_mode: "auto" | "page" | "textbook"
preprocess: boolean
```

返回增加：

```json
{
  "quality": {
    "level": "high | medium | low",
    "chinese_ratio": 0.72,
    "noise_count": 4,
    "needs_review": true
  },
  "regions": [
    {
      "name": "study_box",
      "label": "材料研读",
      "text": "...",
      "quality_level": "medium"
    }
  ],
  "warnings": [
    "图片 OCR 结果可能存在错字，请校对人名、年份、书名后再生成。"
  ]
}
```

为了兼容前端，保留现有：

- `text`
- `pages`
- `warnings`

## 前端优化建议

### 文件

`frontend/app/material-upload/page.tsx`

### 新增 UI

1. OCR 模式选择：
   - 自动
   - 教材页优化
   - 普通整页

2. 识别质量条：
   - 高：可直接校对生成。
   - 中：建议检查关键名词。
   - 低：不建议直接生成。

3. 疑似错字提示：
   - 人名
   - 年份
   - 书名
   - 英文乱码

4. 生成按钮前提示：
   - 如果 `needs_review=true`，按钮文案显示：
     - “我已校对，继续生成”
   - 如果文本很短或质量低，显示二次确认提示。

### 文案建议

低质量 OCR：

```text
这是一份图片识别草稿，系统检测到可能的错字或乱码。请重点校对人名、年份、书名后再生成学习内容。
```

中等质量 OCR：

```text
识别结果基本可用，但图片 OCR 可能存在少量错字，请确认后生成。
```

高质量文本型 PDF：

```text
该资料来自 PDF 文本抽取，可靠性较高，仍建议快速浏览确认。
```

## 推荐实施顺序

### Milestone A：低成本可靠性提升

1. 后端新增图片预处理。
2. Tesseract 使用 `--oem 3 --psm 6`。
3. 失败时 fallback 到原图 + `--psm 4`。
4. 返回 OCR 质量 warning。
5. 前端展示“图片 OCR 需校对”提示。

验收：

- 示例教材截图中，正文段落明显少乱码。
- 不再把 `PERRY`、`HELLS CREE` 等乱码直接混入主文本。
- 前端明确提示需校对。

### Milestone B：教材页分区识别

1. `parse` 接口支持 `ocr_mode=textbook`。
2. 后端按教材页比例切分区域。
3. 分区域 OCR 后按阅读顺序合并。
4. 前端展示区域标签。

验收：

- 材料研读框和正文能分开显示。
- 图片说明区噪声不影响正文主段落。
- 用户能快速定位需要修正的区域。

### Milestone C：实体纠错与风险标注

1. 增加历史实体纠错词表。
2. 增加年份/书名标点修复。
3. 返回被修正项和疑似错字。
4. 前端显示“自动修正记录”。

验收：

- `孙狗仙` 等明显 OCR 错字可被修正为 `孙逸仙`。
- `1875一1905` 修复为 `1875—1905`。
- 自动修正项可被用户看到并继续编辑。

## 验证方案

### 测试材料

至少准备：

1. 文本型 PDF。
2. 清晰教材截图。
3. 手机拍摄教材照片。
4. 低清晰度截图。
5. 混合图片、图注、正文、材料框的教材页。

### 后端验证

```bash
PYTHONPATH=backend /Users/cengjiguang/.local/python3.12/bin/python3 -m py_compile backend/materials/service.py backend/api/main.py
```

手动调用 parse：

```bash
curl -X POST http://localhost:8000/api/materials/parse \
  -H "Authorization: Bearer <token>" \
  -F "file=@/path/to/textbook.png" \
  -F "grade=八年级" \
  -F "subject=历史" \
  -F "ocr_mode=textbook"
```

检查：

- `text` 是否更干净。
- `warnings` 是否合理。
- `quality.needs_review` 是否符合实际。
- `regions` 是否按阅读顺序输出。

### 前端验证

```bash
npm run lint --prefix frontend
npm run build --prefix frontend
npm run dev
```

浏览器测试：

1. 打开 `/material-upload`。
2. 上传教材截图。
3. 查看 OCR 质量提示。
4. 检查区域化文本是否易于校对。
5. 修正文稿后生成学习内容。
6. 确认生成内容不再引用明显 OCR 乱码。

## 风险与取舍

### Tesseract 上限

Tesseract 对教材截图、复杂版面和低清照片仍有明显上限。即使做预处理和分区，也无法保证完全准确。

### 多模态模型方案

更高可靠性的方向是：

1. 用多模态模型直接读取图片，生成转写文本。
2. 再用 OCR 结果做交叉校验。
3. 最后由用户确认。

但这会增加模型成本和响应时间，建议作为后续 Level 或高级模式。

### 结构化教材匹配方案

如果上传内容来自项目已有教材材料，最可靠方式是：

1. 通过 OCR 识别页码、章节标题、关键词。
2. 匹配 `textbooks/structured/*.yaml` 或知识库内容。
3. 用结构化教材文本替代 OCR 草稿。

该方案可靠性最高，但需要额外做教材页匹配逻辑。

## 最终建议

近期优先实现 Milestone A 和 B：

1. 图片预处理。
2. Tesseract 参数优化。
3. 教材页分区 OCR。
4. OCR 质量提示。

这四项能以较低成本显著改善当前教材截图识别结果，并保持 Level 1 MVP 的产品边界清晰：

> 图片 OCR 不是最终事实来源，而是可校对的资料草稿；用户确认后的文本才进入学习内容生成。
