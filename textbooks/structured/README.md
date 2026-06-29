# 人教版历史教材结构化录入

此目录存放人工整理后的教材 YAML。原始 OCR 文本和扫描件不要提交到仓库。

每册一本文件，例如 `七上.yaml`：

```yaml
grade: 七年级上
book: 中国历史七年级上册（人教版）
units:
  - title: 第一单元 史前时期：原始社会与中华文明的起源
    lessons:
      - title: 第1课 远古时期的人类活动
        items:
          - text: "北京人生活在距今约70万至20万年，使用打制石器，已学会使用火，过着群居生活。"
            topic: 北京人
            type: textbook
            page: 4
            tags: [北京人, 旧石器时代, 用火]
            entities: [北京人]
            event: 北京人生活
            period: 史前时期
            keywords: [打制石器, 群居生活, 使用火]
```

## 顶层字段

- `grade`：册别/年级，例如 `七年级上`、`八年级上`、`九年级下`。
- `book`：教材名称，例如 `中国历史七年级上册（人教版）`。
- `units`：单元列表。

## 单元字段

- `title`：单元标题。
- `lessons`：课程列表。

## 课程字段

- `title`：课标题。
- `items`：知识条目列表。

## 知识条目字段

必填：

- `text`：进入 RAG 的正文内容。
- `topic`：该条知识点的核心主题，尽量短且稳定，例如 `虎门销烟`、`商鞅变法`。
- `type`：条目类型，可选 `textbook`、`primary`、`timeline`、`concept`。
- `page`：页码或页码范围。

可选但推荐补齐，用于精准 RAG 命中：

- `tags`：相关标签，适合放同义词、考点词和主题词。
- `entities`：历史人物、国家、组织、地点等实体。
- `event`：对应历史事件。
- `period`：时代/时期，例如 `战国`、`晚清`、`古代埃及`。
- `keywords`：正文中不一定完整出现、但适合检索命中的关键词。
- `source`：来源。缺省时会使用 `《{book}》正文`。

所有条目都会在解析时自动生成基础精准 RAG metadata：

- `event` 默认使用 `topic`。
- `period` 默认从课程标题或单元标题派生。
- `tags` 默认由 `topic`、课程标题、单元标题派生。
- `entities` 默认会包含较短的 `topic`，并尝试从正文中抽取常见历史人物/称号。
- `keywords` 默认由 `topic` 和课程标题派生。

人工填写的 `tags`、`entities`、`event`、`period`、`keywords` 会与自动派生值合并，用于增强精准度，而不是只给少数核心条目使用。

`tags`、`entities`、`keywords` 可以写成列表，也可以写成逗号分隔字符串；解析脚本会统一转成列表。

## 转换命令

```bash
python3 scripts/parse_textbook.py
python3 build_index.py
```

`parse_textbook.py` 默认会替换上一次由结构化教材生成的 corpus 条目，避免只改 metadata 但正文不变时旧 metadata 残留。

如果需要保留旧 structured 条目并只追加新条目，可以使用：

```bash
python3 scripts/parse_textbook.py --keep-existing-structured
```

## 精准 RAG 建议

为了提高检索命中率，每个知识条目建议至少补齐：

```yaml
topic: 虎门销烟
tags: [虎门销烟, 禁烟运动, 鸦片]
entities: [林则徐]
event: 虎门销烟
period: 晚清
keywords: [中国人民禁烟斗争, 反抗外来侵略]
```

这样问题如“林则徐为什么禁烟”“虎门销烟体现什么精神”“鸦片输入有什么危害”都更容易命中正确材料。
