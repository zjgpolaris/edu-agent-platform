"use client";

import { FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { apiUrl } from "@/lib/api";
import { postJsonSse, type SseEvent } from "@/lib/sse";

type Source = {
  rank?: number;
  topic?: string;
  source?: string;
  grade?: string;
  unit?: string;
  lesson?: string;
  page?: string;
  type?: string;
  content?: string;
  snippet?: string;
  score?: number;
  final_score?: number;
  retrieval_score?: number | null;
  keyword_score?: number | null;
  vector_rank?: number | null;
  vector_rank_score?: number | null;
  rerank_score?: number | null;
  source_mode?: string;
  citation_label?: string;
  used_in_answer?: boolean;
  unused_reason?: string | null;
  matched_queries?: string[];
};

type RagInspector = {
  original_question?: string;
  rewritten_query?: string;
  expanded_queries?: string[];
  retrieval_strategy?: string;
  source_count?: number;
};

type CharacterResponse = {
  response: string;
  character: string;
  sources: Source[];
  rag_inspector?: RagInspector;
  verified: boolean;
};

type SelectionMode = "character" | "question";
type CoverageLevel = "high" | "medium" | "low" | "unknown";
type ChatMessageStatus = "drafting" | "verifying" | "verified" | "unverified";

type CharacterPreset = {
  name: string;
  dynastyOrPeriod: string;
  periodGroup: string;
  tags: string[];
  defaultQuestion: string;
  suggestedQuestions: string[];
  featured?: boolean;
};

type RecommendedCharacter = {
  name: string;
  dynastyOrPeriod: string;
  reason: string;
  suggestedQuestion: string;
  coverageLevel: CoverageLevel;
  matchedTopics: string[];
  inCatalog: boolean;
};

type RecommendApiItem = {
  name: string;
  dynasty_or_period: string;
  reason: string;
  suggested_question: string;
  coverage_level: CoverageLevel;
  matched_topics: string[];
  in_catalog?: boolean;
};

type ChatMessage = {
  id: string;
  role: "student" | "agent";
  character?: string;
  content: string;
  sources?: Source[];
  ragInspector?: RagInspector;
  verified?: boolean;
  status?: ChatMessageStatus;
  createdAt: number;
};

const characterPresets: CharacterPreset[] = [
  {
    name: "商鞅",
    dynastyOrPeriod: "战国 · 秦国",
    periodGroup: "推荐人物",
    tags: ["变法", "制度改革", "富国强兵"],
    defaultQuestion: "你为什么要变法？",
    suggestedQuestions: ["你为什么要变法？", "变法对秦国有什么影响？", "为什么变法会遇到阻力？"],
    featured: true,
  },
  {
    name: "秦始皇",
    dynastyOrPeriod: "秦朝",
    periodGroup: "推荐人物",
    tags: ["统一六国", "统一文字", "中央集权"],
    defaultQuestion: "统一文字为什么重要？",
    suggestedQuestions: ["统一文字为什么重要？", "郡县制有什么作用？", "统一六国后做了哪些措施？"],
    featured: true,
  },
  {
    name: "唐太宗",
    dynastyOrPeriod: "唐朝",
    periodGroup: "推荐人物",
    tags: ["贞观之治", "治国策略", "纳谏"],
    defaultQuestion: "什么是贞观之治？",
    suggestedQuestions: ["什么是贞观之治？", "你为什么重视纳谏？", "唐朝前期为什么能出现盛世？"],
    featured: true,
  },
  {
    name: "林则徐",
    dynastyOrPeriod: "清朝",
    periodGroup: "推荐人物",
    tags: ["虎门销烟", "鸦片战争", "民族危机"],
    defaultQuestion: "虎门销烟有什么历史意义？",
    suggestedQuestions: ["虎门销烟有什么历史意义？", "为什么清政府要禁烟？", "鸦片输入带来了什么影响？"],
    featured: true,
  },
  {
    name: "孙中山",
    dynastyOrPeriod: "近代中国",
    periodGroup: "推荐人物",
    tags: ["辛亥革命", "民族民主革命", "三民主义"],
    defaultQuestion: "为什么要推翻清朝？",
    suggestedQuestions: ["为什么要推翻清朝？", "辛亥革命有什么历史意义？", "三民主义主要包括什么？"],
    featured: true,
  },
  {
    name: "孔子",
    dynastyOrPeriod: "春秋时期",
    periodGroup: "中国古代史",
    tags: ["儒家", "教育", "思想"],
    defaultQuestion: "你为什么重视教育？",
    suggestedQuestions: ["你为什么重视教育？", "儒家思想有什么影响？", "你怎么看礼与仁？"],
  },
  {
    name: "孟子",
    dynastyOrPeriod: "战国时期",
    periodGroup: "中国古代史",
    tags: ["仁政", "民本", "儒家"],
    defaultQuestion: "你为什么主张仁政？",
    suggestedQuestions: ["你为什么主张仁政？", "你怎么看民贵君轻？", "儒家思想为什么能延续？"],
  },
  {
    name: "汉武帝",
    dynastyOrPeriod: "西汉",
    periodGroup: "中国古代史",
    tags: ["大一统", "推恩令", "开拓疆域"],
    defaultQuestion: "推恩令有什么作用？",
    suggestedQuestions: ["推恩令有什么作用？", "你为什么重视大一统？", "派张骞出使西域有什么意义？"],
  },
  {
    name: "张骞",
    dynastyOrPeriod: "西汉",
    periodGroup: "中国古代史",
    tags: ["西域", "丝绸之路", "交流"],
    defaultQuestion: "出使西域为什么重要？",
    suggestedQuestions: ["出使西域为什么重要？", "丝绸之路有什么作用？", "你一路上遇到了什么困难？"],
  },
  {
    name: "司马迁",
    dynastyOrPeriod: "西汉",
    periodGroup: "中国古代史",
    tags: ["史记", "史学", "纪传体"],
    defaultQuestion: "你为什么要写《史记》？",
    suggestedQuestions: ["你为什么要写《史记》？", "《史记》有什么价值？", "史书为什么重要？"],
  },
  {
    name: "曹操",
    dynastyOrPeriod: "东汉末年 · 魏国奠基",
    periodGroup: "中国古代史",
    tags: ["三国", "曹魏", "统一北方"],
    defaultQuestion: "你为什么能够统一北方？",
    suggestedQuestions: ["你为什么能够统一北方？", "曹魏为什么在三国中占优势？", "三国格局是怎样形成的？"],
  },
  {
    name: "诸葛亮",
    dynastyOrPeriod: "三国 · 蜀汉",
    periodGroup: "中国古代史",
    tags: ["三国", "蜀汉", "治国"],
    defaultQuestion: "你怎样看待三国鼎立？",
    suggestedQuestions: ["你怎样看待三国鼎立？", "蜀汉为什么难以完成统一？", "北伐为什么屡次进行？"],
  },
  {
    name: "司马炎",
    dynastyOrPeriod: "西晋",
    periodGroup: "中国古代史",
    tags: ["三国归晋", "西晋统一", "西晋"],
    defaultQuestion: "西晋为什么能够结束三国分裂？",
    suggestedQuestions: ["西晋为什么能够结束三国分裂？", "三国为什么最终归于西晋？", "统一后西晋面临了哪些问题？"],
  },
  {
    name: "北魏孝文帝",
    dynastyOrPeriod: "北魏",
    periodGroup: "中国古代史",
    tags: ["改革", "汉化", "民族交融"],
    defaultQuestion: "你为什么要进行改革？",
    suggestedQuestions: ["你为什么要进行改革？", "汉化改革有什么影响？", "改革为什么能促进民族交融？"],
  },
  {
    name: "隋文帝",
    dynastyOrPeriod: "隋朝",
    periodGroup: "中国古代史",
    tags: ["统一", "改革", "开皇之治"],
    defaultQuestion: "统一全国有什么意义？",
    suggestedQuestions: ["统一全国有什么意义？", "你采取了哪些治国措施？", "隋朝为什么能结束分裂？"],
  },
  {
    name: "武则天",
    dynastyOrPeriod: "唐朝",
    periodGroup: "中国古代史",
    tags: ["治国", "用人", "承前启后"],
    defaultQuestion: "你为什么重视选拔人才？",
    suggestedQuestions: ["你为什么重视选拔人才？", "你的统治对唐朝有什么影响？", "你怎么看打破旧有门第限制？"],
  },
  {
    name: "岳飞",
    dynastyOrPeriod: "南宋",
    periodGroup: "中国古代史",
    tags: ["抗金", "爱国", "民族关系"],
    defaultQuestion: "你为什么坚持抗金？",
    suggestedQuestions: ["你为什么坚持抗金？", "南宋为什么面临北方压力？", "你怎么看精忠报国？"],
  },
  {
    name: "郑和",
    dynastyOrPeriod: "明朝",
    periodGroup: "中国古代史",
    tags: ["下西洋", "航海", "交流"],
    defaultQuestion: "下西洋有什么意义？",
    suggestedQuestions: ["下西洋有什么意义？", "明朝为什么能组织远航？", "远航促进了哪些交流？"],
  },
  {
    name: "康熙",
    dynastyOrPeriod: "清朝",
    periodGroup: "中国古代史",
    tags: ["统一多民族国家", "治理", "收复台湾"],
    defaultQuestion: "你为什么重视国家统一？",
    suggestedQuestions: ["你为什么重视国家统一？", "收复台湾有什么意义？", "清朝前期为什么能稳定局势？"],
  },
  {
    name: "洪秀全",
    dynastyOrPeriod: "晚清",
    periodGroup: "中国近现代史",
    tags: ["太平天国", "农民运动", "反清"],
    defaultQuestion: "太平天国运动为什么会爆发？",
    suggestedQuestions: ["太平天国运动为什么会爆发？", "太平天国运动有哪些影响？", "晚清社会为什么动荡？"],
  },
  {
    name: "李鸿章",
    dynastyOrPeriod: "晚清",
    periodGroup: "中国近现代史",
    tags: ["洋务运动", "近代化", "外交"],
    defaultQuestion: "洋务运动为什么要兴办近代工业？",
    suggestedQuestions: ["洋务运动为什么要兴办近代工业？", "甲午战争失败说明了什么？", "晚清近代化遇到了哪些问题？"],
  },
  {
    name: "康有为",
    dynastyOrPeriod: "晚清",
    periodGroup: "中国近现代史",
    tags: ["维新变法", "戊戌变法", "改革"],
    defaultQuestion: "你为什么主张变法？",
    suggestedQuestions: ["你为什么主张变法？", "戊戌变法为什么失败？", "维新派想解决什么问题？"],
  },
  {
    name: "梁启超",
    dynastyOrPeriod: "晚清",
    periodGroup: "中国近现代史",
    tags: ["维新", "启蒙", "变法"],
    defaultQuestion: "你为什么提倡新思想？",
    suggestedQuestions: ["你为什么提倡新思想？", "维新思想对近代中国有什么影响？", "启蒙为什么重要？"],
  },
  {
    name: "陈独秀",
    dynastyOrPeriod: "近代中国",
    periodGroup: "中国近现代史",
    tags: ["新文化运动", "民主", "科学"],
    defaultQuestion: "为什么要发起新文化运动？",
    suggestedQuestions: ["为什么要发起新文化运动？", "新文化运动有什么影响？", "为什么提倡民主与科学？"],
  },
  {
    name: "李大钊",
    dynastyOrPeriod: "近代中国",
    periodGroup: "中国近现代史",
    tags: ["马克思主义", "五四", "思想传播"],
    defaultQuestion: "为什么要传播马克思主义？",
    suggestedQuestions: ["为什么要传播马克思主义？", "新文化运动为什么会走向新阶段？", "五四运动带来了什么影响？"],
  },
  {
    name: "毛泽东",
    dynastyOrPeriod: "现代中国",
    periodGroup: "中国近现代史",
    tags: ["革命", "新民主主义", "建国"],
    defaultQuestion: "为什么要走新民主主义革命道路？",
    suggestedQuestions: ["为什么要走新民主主义革命道路？", "抗日战争为什么能取得胜利？", "中华人民共和国成立有什么意义？"],
  },
  {
    name: "周恩来",
    dynastyOrPeriod: "现代中国",
    periodGroup: "中国近现代史",
    tags: ["外交", "革命", "合作"],
    defaultQuestion: "你为什么重视外交工作？",
    suggestedQuestions: ["你为什么重视外交工作？", "新中国初期为什么要加强国际交往？", "合作在革命和建设中有什么作用？"],
  },
  {
    name: "邓小平",
    dynastyOrPeriod: "现代中国",
    periodGroup: "中国近现代史",
    tags: ["改革开放", "现代化", "发展"],
    defaultQuestion: "为什么要实行改革开放？",
    suggestedQuestions: ["为什么要实行改革开放？", "改革开放怎样改变了中国？", "现代化建设为什么重要？"],
  },
  {
    name: "伯里克利",
    dynastyOrPeriod: "古代希腊",
    periodGroup: "世界史",
    tags: ["民主政治", "雅典", "公民"],
    defaultQuestion: "雅典民主政治有什么特点？",
    suggestedQuestions: ["雅典民主政治有什么特点？", "为什么雅典能发展民主？", "古希腊民主有哪些局限？"],
  },
  {
    name: "亚历山大",
    dynastyOrPeriod: "马其顿",
    periodGroup: "世界史",
    tags: ["东征", "帝国", "文化传播"],
    defaultQuestion: "东征带来了什么影响？",
    suggestedQuestions: ["东征带来了什么影响？", "为什么你的征服会促进交流？", "希腊文化如何传播？"],
  },
  {
    name: "凯撒",
    dynastyOrPeriod: "古罗马",
    periodGroup: "世界史",
    tags: ["罗马", "独裁", "共和国危机"],
    defaultQuestion: "罗马共和国为什么会走向危机？",
    suggestedQuestions: ["罗马共和国为什么会走向危机？", "你为什么能掌握大权？", "罗马政治转型说明了什么？"],
  },
  {
    name: "哥伦布",
    dynastyOrPeriod: "15世纪末",
    periodGroup: "世界史",
    tags: ["新航路", "地理大发现", "殖民扩张"],
    defaultQuestion: "新航路开辟为什么重要？",
    suggestedQuestions: ["新航路开辟为什么重要？", "为什么欧洲人要进行远洋航行？", "新航路开辟带来了哪些影响？"],
  },
  {
    name: "华盛顿",
    dynastyOrPeriod: "美国独立战争时期",
    periodGroup: "世界史",
    tags: ["独立战争", "美国", "共和"],
    defaultQuestion: "美国为什么要争取独立？",
    suggestedQuestions: ["美国为什么要争取独立？", "独立战争有什么意义？", "你怎么看共和制度？"],
  },
  {
    name: "拿破仑",
    dynastyOrPeriod: "法国",
    periodGroup: "世界史",
    tags: ["法国大革命", "法典", "帝国"],
    defaultQuestion: "拿破仑法典有什么意义？",
    suggestedQuestions: ["拿破仑法典有什么意义？", "法国大革命为什么会改变欧洲？", "你的战争带来了什么影响？"],
  },
  {
    name: "马克思",
    dynastyOrPeriod: "19世纪欧洲",
    periodGroup: "世界史",
    tags: ["马克思主义", "工人运动", "社会主义"],
    defaultQuestion: "你为什么关注工人阶级？",
    suggestedQuestions: ["你为什么关注工人阶级？", "马克思主义为什么会产生？", "工业革命带来了哪些社会问题？"],
  },
  {
    name: "列宁",
    dynastyOrPeriod: "20世纪初俄国",
    periodGroup: "世界史",
    tags: ["十月革命", "俄国", "社会主义"],
    defaultQuestion: "十月革命为什么会发生？",
    suggestedQuestions: ["十月革命为什么会发生？", "俄国为什么会走上革命道路？", "十月革命有什么历史意义？"],
  },
];

const progressSteps = ["检索初中历史史料", "生成教学模拟回答", "进行史实一致性检查"];
const featuredPresets = characterPresets.filter((preset) => preset.featured);
const initialPreset = featuredPresets[0];
const groupOrder = ["推荐人物", "中国古代史", "中国近现代史", "世界史"];

function createId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function getFriendlyErrorMessage(error: unknown) {
  if (error instanceof TypeError) {
    return "无法连接后端服务，请确认已在项目根目录运行 npm run dev。";
  }

  if (error instanceof Error && error.message.includes("HTTP 500")) {
    return "后端生成回答时出错，可能是模型 Key、模型服务或知识库加载异常。请查看后端终端日志。";
  }

  if (error instanceof Error && error.message.includes("HTTP 422")) {
    return "请求内容格式不正确，请检查历史人物和问题是否填写完整。";
  }

  if (error instanceof Error && error.message) {
    return error.message;
  }

  return "请求失败，请稍后重试。";
}

function validateInput(character: string, message: string) {
  if (!character) return "请先输入你想提问的历史人物。";
  if (!message) return "请写下你的问题，例如：“你为什么要变法？”";
  if (message.length < 2) return "问题太短了，可以写得更具体一点。";
  if (message.length > 300) return "问题有点长，建议拆成多个小问题继续追问。";
  return "";
}

function getSourceTypeLabel(type?: string) {
  if (type === "primary") return "原始史料";
  if (type === "secondary") return "教材/解释材料";
  return "未标注";
}

function getProgressStep(phase: unknown) {
  if (phase === "retrieving") return 0;
  if (phase === "generating") return 1;
  if (phase === "verifying") return 2;
  if (phase === "done") return progressSteps.length;
  return -1;
}

function asRagInspector(value: unknown): RagInspector | null {
  if (!value || typeof value !== "object") return null;
  const item = value as RagInspector;
  return {
    original_question: typeof item.original_question === "string" ? item.original_question : undefined,
    rewritten_query: typeof item.rewritten_query === "string" ? item.rewritten_query : undefined,
    expanded_queries: Array.isArray(item.expanded_queries) ? item.expanded_queries.filter((q): q is string => typeof q === "string") : undefined,
    retrieval_strategy: typeof item.retrieval_strategy === "string" ? item.retrieval_strategy : undefined,
    source_count: typeof item.source_count === "number" ? item.source_count : undefined,
  };
}

function formatScore(value?: number | null) {
  return typeof value === "number" ? value.toFixed(3) : "-";
}

function getRetrievalStrategyLabel(strategy?: string) {
  if (strategy === "tool_primary") return "主检索工具";
  if (strategy === "multi_query_fallback") return "多查询兜底";
  if (strategy === "retriever_fallback") return "基础检索兜底";
  return strategy || "未知策略";
}

function getCoverageCopy(level: CoverageLevel, inCatalog = true) {
  if (!inCatalog) return "该人物不在预设目录中，可尝试对话，但史料覆盖可能有限，请重点查看右侧史料依据。";
  if (level === "high") return "资料较充分，适合进行人物对话。";
  if (level === "medium") return "有一定资料，可围绕教材重点提问。";
  if (level === "low") return "资料较少，建议提出更具体的问题。";
  return "当前知识库覆盖不明确，回答需结合史料依据判断。";
}

function getCoverageBadge(level: CoverageLevel) {
  if (level === "high") return "资料充分";
  if (level === "medium") return "资料较全";
  if (level === "low") return "资料有限";
  return "覆盖待确认";
}

export default function Home() {
  const searchParams = useSearchParams();
  const [selectionMode, setSelectionMode] = useState<SelectionMode>("character");
  const [selectedCharacter, setSelectedCharacter] = useState(initialPreset.name);
  const [character, setCharacter] = useState(initialPreset.name);
  const [message, setMessage] = useState(searchParams.get("q") ?? initialPreset.defaultQuestion);
  const [recommendQuestion, setRecommendQuestion] = useState("");
  const [recommendedCharacters, setRecommendedCharacters] = useState<RecommendedCharacter[]>([]);
  const [recommendLoading, setRecommendLoading] = useState(false);
  const [recommendError, setRecommendError] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activeSources, setActiveSources] = useState<Source[]>([]);
  const [activeInspector, setActiveInspector] = useState<RagInspector | null>(null);
  const [activeMessageId, setActiveMessageId] = useState<string>("");
  const [status, setStatus] = useState("选择人物并提出问题，系统会基于史料进行教学模拟回答。");
  const [errorMessage, setErrorMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [progressStep, setProgressStep] = useState(-1);
  const [progressFailed, setProgressFailed] = useState(false);
  const [showAllSources, setShowAllSources] = useState(false);
  const [sourcesOpen, setSourcesOpen] = useState(true);
  const [expandedSources, setExpandedSources] = useState<Record<string, boolean>>({});
  const [copyStatus, setCopyStatus] = useState("");
  const [agentSteps, setAgentSteps] = useState<string[]>([]);
  const [toastMsg, setToastMsg] = useState("");
  const [toastFading, setToastFading] = useState(false);
  const [chatAtBottom, setChatAtBottom] = useState(true);
  const [characterSearch, setCharacterSearch] = useState("");
  const [activeMobilePanel, setActiveMobilePanel] = useState<"sidebar" | "chat" | "sources">("chat");

  const chatStreamRef = useRef<HTMLDivElement>(null);
  const chatBottomRef = useRef<HTMLDivElement>(null);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = useCallback((msg: string) => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setToastMsg(msg);
    setToastFading(false);
    toastTimerRef.current = setTimeout(() => {
      setToastFading(true);
      toastTimerRef.current = setTimeout(() => setToastMsg(""), 280);
    }, 1800);
  }, []);

  const updateChatScrollState = useCallback(() => {
    const node = chatStreamRef.current;
    if (!node) return;
    const distanceToBottom = node.scrollHeight - node.scrollTop - node.clientHeight;
    setChatAtBottom(distanceToBottom < 24);
  }, []);

  useEffect(() => {
    if (chatAtBottom && messages.length > 0) {
      chatBottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
    requestAnimationFrame(updateChatScrollState);
  }, [messages, chatAtBottom, updateChatScrollState]);

  useEffect(() => {
    return () => {
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    };
  }, []);

  const activePreset = useMemo(() => {
    const typedCharacter = character.trim();
    const typedMatch = characterPresets.find((preset) => preset.name === typedCharacter);
    if (typedMatch) return typedMatch;
    if (typedCharacter && typedCharacter !== selectedCharacter) return null;
    return characterPresets.find((preset) => preset.name === selectedCharacter) || null;
  }, [character, selectedCharacter]);

  const groupedPresets = useMemo(
    () =>
      groupOrder
        .map((groupName) => ({
          groupName,
          items: groupName === "推荐人物"
            ? featuredPresets
            : characterPresets.filter((preset) => preset.periodGroup === groupName),
        }))
        .filter((group) => group.items.length > 0),
    [],
  );

  const filteredGroupedPresets = useMemo(() => {
    const q = characterSearch.trim();
    if (!q) return groupedPresets;
    return groupedPresets
      .map((group) => ({
        ...group,
        items: group.items.filter((p) =>
          p.name.includes(q) || p.dynastyOrPeriod.includes(q) || p.tags.some((t) => t.includes(q))
        ),
      }))
      .filter((group) => group.items.length > 0);
  }, [groupedPresets, characterSearch]);

  function updateAgentMessage(messageId: string, updater: (item: ChatMessage) => ChatMessage) {
    setMessages((current) => current.map((item) => (item.id === messageId ? updater(item) : item)));
  }

  function selectPreset(preset: CharacterPreset) {
    setSelectedCharacter(preset.name);
    setCharacter(preset.name);
    setMessage(preset.defaultQuestion);
    setStatus(`已切换到${preset.name}，可以选择推荐问题或直接提问。`);
    setErrorMessage("");
  }

  function handleSuggestedQuestion(question: string) {
    setMessage(question);
    setStatus("已填入推荐问题，点击“开始对话”后生成回答。");
    setErrorMessage("");
  }

  function clearConversation() {
    setMessages([]);
    setActiveSources([]);
    setActiveInspector(null);
    setActiveMessageId("");
    setErrorMessage("");
    setCopyStatus("");
    setProgressStep(-1);
    setStatus("已清空当前页面对话，可以重新开始提问。");
  }

  async function copyAnswer(content: string) {
    try {
      await navigator.clipboard.writeText(content);
      showToast("回答已复制");
      setCopyStatus("回答已复制。");
    } catch {
      showToast("复制失败，请手动选择文本复制");
      setCopyStatus("复制失败，请手动选择文本复制。");
    }
  }

  async function recommendCharactersForQuestion() {
    const trimmedQuestion = recommendQuestion.trim();
    if (!trimmedQuestion) {
      setRecommendError("请先输入你想了解的历史问题。");
      setRecommendedCharacters([]);
      return;
    }

    setRecommendLoading(true);
    setRecommendError("");
    setRecommendedCharacters([]);
    setStatus("正在根据问题匹配合适的历史人物视角...");

    try {
      const response = await fetch(apiUrl("/api/history/character/recommend"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: trimmedQuestion, grade: null, limit: 4 }),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = (await response.json()) as { recommendations?: RecommendApiItem[] };
      const items = Array.isArray(data.recommendations) ? data.recommendations : [];
      setRecommendedCharacters(
        items.map((item) => ({
          name: item.name,
          dynastyOrPeriod: item.dynasty_or_period,
          reason: item.reason,
          suggestedQuestion: item.suggested_question,
          coverageLevel: item.coverage_level,
          matchedTopics: item.matched_topics || [],
          inCatalog: item.in_catalog ?? true,
        })),
      );
      setStatus(items.length ? "模型已推荐适合的人物视角，目录外人物会标注资料覆盖风险。" : "暂时没有找到明显匹配的人物，你也可以直接输入人物开始提问。");
    } catch (error) {
      setRecommendError(getFriendlyErrorMessage(error));
      setStatus("推荐接口暂时不可用，你仍然可以手动选择或输入人物。");
    } finally {
      setRecommendLoading(false);
    }
  }

  function selectRecommendedCharacter(item: RecommendedCharacter) {
    setSelectedCharacter(item.name);
    setCharacter(item.name);
    setMessage(item.suggestedQuestion || recommendQuestion.trim());
    setSelectionMode("character");
    setStatus(item.inCatalog ? `已选择${item.name}，可以直接开始对话，也可以修改问题。` : `已选择目录外人物${item.name}，可尝试对话，请重点查看史料依据。`);
    setErrorMessage("");
  }

  function handleCharacterChange(value: string) {
    setCharacter(value);
    const trimmedValue = value.trim();
    const matchedPreset = characterPresets.find((preset) => preset.name === trimmedValue);
    setSelectedCharacter(matchedPreset ? matchedPreset.name : "");
  }

  async function handleStreamEvent(streamEvent: SseEvent, agentMessageId: string) {
    const { event, data } = streamEvent;

    if (event === "status") {
      const step = getProgressStep(data.phase);
      setProgressStep(step);
      if (typeof data.message === "string") {
        const message = data.message;
        setStatus(message);
        setAgentSteps((prev) => [...prev, message]);
      }
      if (data.phase === "verifying") {
        updateAgentMessage(agentMessageId, (item) => ({ ...item, status: "verifying" }));
      }
      return;
    }

    if (event === "sources") {
      const sources = Array.isArray(data.sources) ? (data.sources as Source[]) : [];
      const inspector = asRagInspector(data.inspector);
      setActiveSources(sources);
      setActiveInspector(inspector);
      setShowAllSources(false);
      updateAgentMessage(agentMessageId, (item) => ({ ...item, sources, ragInspector: inspector || item.ragInspector }));
      return;
    }

    if (event === "delta") {
      const text = typeof data.text === "string" ? data.text : "";
      updateAgentMessage(agentMessageId, (item) => ({ ...item, content: item.content + text, status: "drafting" }));
      return;
    }

    if (event === "final") {
      const finalData = data as CharacterResponse;
      const sources = Array.isArray(finalData.sources) ? finalData.sources : [];
      const inspector = asRagInspector(finalData.rag_inspector);
      setActiveSources(sources);
      setActiveInspector(inspector);
      setShowAllSources(false);
      setProgressStep(progressSteps.length);
      setStatus(finalData.verified ? "已完成，并通过史实一致性检查。" : "已完成，建议结合史料继续复核。");
      updateAgentMessage(agentMessageId, (item) => ({
        ...item,
        character: finalData.character || item.character,
        content: finalData.response || item.content,
        sources,
        ragInspector: inspector || item.ragInspector,
        verified: Boolean(finalData.verified),
        status: finalData.verified ? "verified" : "unverified",
      }));
      return;
    }

    if (event === "error") {
      throw new Error(typeof data.message === "string" ? data.message : "流式生成失败，请稍后重试。");
    }
  }

  async function submit(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();

    const trimmedCharacter = character.trim();
    const trimmedMessage = message.trim();
    const validationMessage = validateInput(trimmedCharacter, trimmedMessage);

    if (validationMessage) {
      setErrorMessage(validationMessage);
      setStatus("");
      return;
    }

    setLoading(true);
    setErrorMessage("");
    setCopyStatus("");
    setProgressFailed(false);
    setProgressStep(0);
    setStatus("正在连接后端流式接口...");

    const studentMessage: ChatMessage = {
      id: createId("student"),
      role: "student",
      character: trimmedCharacter,
      content: trimmedMessage,
      createdAt: Date.now(),
    };
    const agentMessage: ChatMessage = {
      id: createId("agent"),
      role: "agent",
      character: trimmedCharacter,
      content: "",
      sources: [],
      status: "drafting",
      createdAt: Date.now(),
    };

    setMessages((current) => [...current, studentMessage, agentMessage]);
    setActiveMessageId(agentMessage.id);
    setActiveSources([]);
    setActiveInspector(null);
    setShowAllSources(false);
    setAgentSteps([]);
    setProgressStep(-1);

    try {
      await postJsonSse("/api/history/character/chat", { character: trimmedCharacter, message: trimmedMessage, stream: true }, {
        fallbackMessage: "流式生成失败，请稍后重试。",
        onEvent: (streamEvent) => handleStreamEvent(streamEvent, agentMessage.id),
      });
    } catch (error) {
      setProgressFailed(true);
      setErrorMessage(getFriendlyErrorMessage(error));
      setStatus("本次未完成史实校验。可以检查服务状态后重试。");
      updateAgentMessage(agentMessage.id, (item) => ({ ...item, status: "unverified", verified: false }));
    } finally {
      setLoading(false);
    }
  }

  function renderSourceCard(source: Source, index: number) {
    const key = `${source.topic || "source"}-${index}`;
    const content = source.content || "暂无史料内容。";
    const isLong = content.length > 120;
    const expanded = expandedSources[key] || !isLong;
    const visibleContent = expanded ? content : `${content.slice(0, 120)}...`;
    const score = source.final_score ?? source.score ?? 0;
    const scorePercent = Math.min(Math.max(score * 100, 0), 100);
    const sourceMode = source.source_mode || "unknown";
    const usedLabel = source.used_in_answer ? "已引用" : source.used_in_answer === false ? "未引用" : "待标记";

    function getSourceModeLabel(mode: string) {
      if (mode === "vector") return "向量检索";
      if (mode === "keyword") return "关键词检索";
      if (mode === "hybrid") return "混合检索";
      return "未知";
    }

    return (
      <article className="source-card" key={key}>
        <div className="source-index" aria-hidden="true">{String(index + 1).padStart(2, "0")}</div>
        <div className="source-card-header">
          <div>
            <div className="source-kicker">史料札记</div>
            <div className="source-title">{source.citation_label ? `${source.citation_label} ` : ""}{source.topic || "未标注主题"}</div>
            <div className="source-meta">{[source.grade, source.unit, source.lesson, source.page ? `第${source.page}页` : "", source.source].filter(Boolean).join(" · ") || "未标注来源"}</div>
          </div>
          <div className="source-badges">
            <span className="source-type">#{source.rank || index + 1}</span>
            <span className="source-type">{getSourceTypeLabel(source.type)}</span>
            <span className="source-mode">{getSourceModeLabel(sourceMode)}</span>
            <span className="source-mode">{usedLabel}</span>
          </div>
        </div>
        {score > 0 && (
          <div className="source-score-bar">
            <div className="score-label">相关度 {scorePercent.toFixed(0)}%</div>
            <div className="score-track">
              <div className="score-fill" style={{ width: `${scorePercent}%` }} />
            </div>
          </div>
        )}
        <details className="source-score-details">
          <summary>检索分解</summary>
          <div className="source-score-grid">
            <span>final {formatScore(source.final_score ?? source.score)}</span>
            <span>retrieval {formatScore(source.retrieval_score)}</span>
            <span>keyword {formatScore(source.keyword_score)}</span>
            <span>vector rank {source.vector_rank ?? "-"}</span>
            <span>vector rank score {formatScore(source.vector_rank_score)}</span>
            <span>rerank {formatScore(source.rerank_score)}</span>
          </div>
        </details>
        {source.unused_reason && <div className="source-unused-reason">{source.unused_reason}</div>}
        <div className="source-content">{visibleContent}</div>
        {isLong && (
          <button
            className="text-button"
            type="button"
            onClick={() => setExpandedSources((current) => ({ ...current, [key]: !expanded }))}
          >
            {expanded ? "收起札记" : "展开全文"}
          </button>
        )}
      </article>
    );
  }

  function getAgentBadge(item: ChatMessage) {
    if (item.status === "drafting") return "生成中";
    if (item.status === "verifying") return "校验中";
    if (item.status === "verified") return "已通过史实校验";
    return item.verified ? "已通过史实校验" : "建议结合史料复核";
  }

  const visibleSources = showAllSources ? activeSources : activeSources.slice(0, 2);

  return (
    <main className="academy-shell history-character-shell">
      {toastMsg && (
        <div className={`copy-toast${toastFading ? " fade-out" : ""}`} aria-live="assertive">
          {toastMsg}
        </div>
      )}
      <section className="academy-hero history-character-hero">
        <div className="hero-copy">
          <div className="eyebrow">初中历史 · Agentic RAG</div>
          <h1>历史人物对话馆</h1>
          <p>你可以直接选择历史人物，也可以先提出一个历史问题，让系统推荐适合对话的人物视角，再进入教学模拟问答。</p>
          <div className="hero-flow" aria-label="学习流程">
            <span>选人物</span>
            <span>问问题</span>
            <span>查史料</span>
            <span>做校验</span>
          </div>
          <div className="hero-ledger" aria-label="对话馆能力">
            <span><b>01</b> 自主选人</span>
            <span><b>02</b> 模型推荐</span>
            <span><b>03</b> 史料校验</span>
          </div>
        </div>
        <div className="teaching-card character-boundary-card" aria-label="当前教学边界说明">
          <div className="seal-mark" aria-hidden="true">史</div>
          <span className="card-label">教学边界</span>
          <strong>这是历史教学模拟</strong>
          <p>回答不是历史人物真实发言，需要结合右侧史料依据和课堂教材继续理解。若人物资料较少，系统会基于已检索到的史料作有限解释。</p>
          <div className="boundary-grid" aria-hidden="true">
            <span>模拟口吻</span>
            <span>证据优先</span>
            <span>可追问</span>
          </div>
        </div>
      </section>

      <div className="mobile-panel-tabs" aria-label="切换面板">
        <button className={`mobile-tab${activeMobilePanel === "sidebar" ? " active" : ""}`} type="button" onClick={() => setActiveMobilePanel("sidebar")}>选人物</button>
        <button className={`mobile-tab${activeMobilePanel === "chat" ? " active" : ""}`} type="button" onClick={() => setActiveMobilePanel("chat")}>对话课堂</button>
        <button className={`mobile-tab${activeMobilePanel === "sources" ? " active" : ""}`} type="button" onClick={() => setActiveMobilePanel("sources")}>史料依据</button>
      </div>

      <section className="workspace academy-workspace">
        <aside className={`sidebar panel character-panel workspace-panel-enter${activeMobilePanel !== "sidebar" ? " mobile-panel-hidden" : ""}`} aria-label="人物选择与推荐入口">
          <div className="panel-heading">
            <div>
              <span className="panel-kicker">第一步</span>
              <h2>人物选择方式</h2>
            </div>
            <small>自主选人优先，问题推荐辅助</small>
          </div>

          <div className="mode-switch" role="tablist" aria-label="人物选择模式">
            <button
              className={`mode-pill ${selectionMode === "character" ? "active" : ""}`}
              type="button"
              onClick={() => setSelectionMode("character")}
              aria-pressed={selectionMode === "character"}
            >
              选择历史人物
            </button>
            <button
              className={`mode-pill ${selectionMode === "question" ? "active" : ""}`}
              type="button"
              onClick={() => setSelectionMode("question")}
              aria-pressed={selectionMode === "question"}
            >
              根据问题推荐
            </button>
          </div>

          {selectionMode === "character" ? (
            <>
              <div className="catalog-note">保留自由输入能力，不局限于下方人物库。</div>
              <input
                className="character-search"
                type="search"
                value={characterSearch}
                onChange={(e) => setCharacterSearch(e.target.value)}
                placeholder="搜索人物、朝代或标签..."
              />
              <div className="character-groups">
                {filteredGroupedPresets.map((group) => (
                  <section className="character-group" key={group.groupName}>
                    <div className="group-heading">
                      <span>{group.groupName}</span>
                      <small>{group.items.length} 位</small>
                    </div>
                    <div className="character-list grouped">
                      {group.items.map((preset) => (
                        <button
                          className={`character-card ${selectedCharacter === preset.name ? "selected" : ""}`}
                          type="button"
                          key={`${group.groupName}-${preset.name}`}
                          onClick={() => selectPreset(preset)}
                          aria-pressed={selectedCharacter === preset.name}
                        >
                          <span className="character-seal" aria-hidden="true">{preset.name.slice(0, 1)}</span>
                          <span className="character-copy">
                            <span className="character-name">{preset.name}</span>
                            <span className="character-period">{preset.dynastyOrPeriod}</span>
                            <span className="tag-row">
                              {preset.tags.map((tag) => (
                                <span className="tag" key={tag}>{tag}</span>
                              ))}
                            </span>
                          </span>
                        </button>
                      ))}
                    </div>
                  </section>
                ))}
                {filteredGroupedPresets.length === 0 && (
                  <div className="character-search-empty">没有找到匹配的人物，可直接在下方输入名称。</div>
                )}
              </div>
                <div className="panel-heading compact">
                  <div>
                    <span className="panel-kicker">第二步</span>
                    <h3>{activePreset ? `${activePreset.name}的推荐问题` : "推荐问题"}</h3>
                  </div>
                </div>
                {activePreset ? (
                  activePreset.suggestedQuestions.map((question) => (
                    <button className="suggestion" type="button" key={question} onClick={() => handleSuggestedQuestion(question)}>
                      <span aria-hidden="true">问</span>
                      {question}
                    </button>
                  ))
                ) : (
                  <div className="recommend-empty">直接在下方输入历史人物后，也可以手动编辑问题开始对话。</div>
                )}
            </>
          ) : (
            <div className="recommend-panel">
              <div className="recommend-intro">
                <strong>我有一个历史问题，不知道该问谁</strong>
                <p>先输入问题，系统会推荐 2–4 位可用于理解这个问题的历史人物视角。</p>
              </div>
              <label htmlFor="recommend-question">我想了解</label>
              <textarea
                id="recommend-question"
                value={recommendQuestion}
                maxLength={160}
                onChange={(event) => setRecommendQuestion(event.target.value)}
                placeholder="例如：为什么秦国能够统一六国？"
              />
              <div className="input-help">{recommendQuestion.length}/160</div>
              <button className="secondary full" type="button" disabled={recommendLoading} onClick={recommendCharactersForQuestion}>
                {recommendLoading ? "推荐人物中..." : "帮我推荐可以对话的人物"}
              </button>

              <div className="recommend-results">
                {recommendLoading && (
                  <div className="recommend-state loading-state">
                    正在匹配相关人物、检索资料覆盖情况，请稍候。
                  </div>
                )}

                {!recommendLoading && recommendError && (
                  <div className="recommend-state error-state" role="alert">
                    <strong>暂时无法完成推荐</strong>
                    <span>{recommendError}</span>
                  </div>
                )}

                {!recommendLoading && !recommendError && recommendedCharacters.length === 0 && recommendQuestion.trim() && (
                  <div className="recommend-state empty-state-card">
                    暂时没有明显匹配的人物。你也可以直接输入人物姓名开始提问。
                  </div>
                )}

                {!recommendLoading && !recommendError && !recommendQuestion.trim() && (
                  <div className="recommend-state empty-state-card">
                    你可以先写下一个历史问题，再从多个相关人物视角中选择。
                  </div>
                )}

                {!recommendLoading && recommendedCharacters.length > 0 && (
                  <div className="recommend-card-list">
                    {recommendedCharacters.map((item) => (
                      <article className="recommend-card" key={`${item.name}-${item.suggestedQuestion}`}>
                        <div className="recommend-card-header">
                          <div>
                            <div className="recommend-name">{item.name}</div>
                            <div className="recommend-period">{item.dynastyOrPeriod}</div>
                            {!item.inCatalog && <span className="catalog-badge">目录外人物</span>}
                          </div>
                          <span className={`coverage-badge ${item.coverageLevel}`}>{getCoverageBadge(item.coverageLevel)}</span>
                        </div>
                        <p className="recommend-reason">{item.reason}</p>
                        {item.matchedTopics.length > 0 && (
                          <div className="tag-row">
                            {item.matchedTopics.map((topic) => (
                              <span className="tag" key={`${item.name}-${topic}`}>{topic}</span>
                            ))}
                          </div>
                        )}
                        <div className="coverage-copy">{getCoverageCopy(item.coverageLevel, item.inCatalog)}</div>
                        <div className="recommend-question">推荐问题：{item.suggestedQuestion}</div>
                        <button className="secondary full" type="button" onClick={() => selectRecommendedCharacter(item)}>
                          用这个人物继续提问
                        </button>
                      </article>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </aside>

        <section className={`chat-panel panel workspace-panel-enter${activeMobilePanel !== "chat" ? " mobile-panel-hidden" : ""}`} aria-label="对话课堂">
          <div className="chat-header">
            <div>
              <span className="panel-kicker">对话课堂</span>
              <h2>向 {character || activePreset?.name || "历史人物"} 提问</h2>
              <p>用课堂讨论的方式提问，回答会在生成后接受史实一致性检查。</p>
            </div>
            <button className="secondary" type="button" disabled={messages.length === 0 && !activeSources.length} onClick={clearConversation}>
              清空对话
            </button>
          </div>

          <div className="current-brief" aria-label="当前对话案头">
            <div className="current-brief-seal" aria-hidden="true">{(character || activePreset?.name || "史").slice(0, 1)}</div>
            <div>
              <span>当前人物</span>
              <strong>{character || activePreset?.name || "自由输入人物"}</strong>
              <p>{activePreset ? `${activePreset.dynastyOrPeriod} · ${activePreset.tags.join(" / ")}` : "目录外人物也可以对话，系统会尽量基于检索史料回答。"}</p>
            </div>
          </div>

          <div className={`chat-stream-wrap ${chatAtBottom ? "at-bottom" : ""}`}>
            <div className="chat-stream" aria-live="polite" ref={chatStreamRef} onScroll={updateChatScrollState}>
            {messages.length === 0 ? (
              <div className="empty-state classroom-empty">
                <span className="empty-stamp" aria-hidden="true">问</span>
                <strong>从一个好问题开始</strong>
                <span>先在左侧选择人物或请求推荐，再直接写下你想追问的历史原因、影响与意义。</span>
              </div>
            ) : (
              messages.map((item) => (
                <article
                  className={`message ${item.role}${item.status ? ` status-${item.status}` : ""} ${activeMessageId === item.id ? "active" : ""}`}
                  key={item.id}
                  onClick={() => {
                    if (item.sources) {
                      setActiveSources(item.sources);
                      setActiveInspector(item.ragInspector || null);
                      setActiveMessageId(item.id);
                      setShowAllSources(false);
                    }
                  }}
                >
                  <div className="message-meta">
                    <span>{item.role === "student" ? "学生提问" : `${item.character || "历史人物"} · 教学模拟回答`}</span>
                    {item.role === "agent" && (
                      <span className={`verify-badge ${item.status || (item.verified ? "verified" : "unverified")}`}>
                        {getAgentBadge(item)}
                      </span>
                    )}
                  </div>
                  <div className="message-content">
                    {item.content || (item.role === "agent" ? "正在等待模型输出..." : "")}
                  </div>
                  {item.role === "agent" && item.sources?.length ? (
                    <div className="message-source-hint" aria-hidden="true">
                      ◎ 点击查看 {item.sources.length} 条史料依据
                    </div>
                  ) : null}
                  {item.role === "agent" && item.content && (
                    <div className="message-actions">
                      <button
                        className="text-button"
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          copyAnswer(item.content);
                        }}
                      >
                        复制回答
                      </button>
                      <button
                        className="text-button"
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          setActiveSources(item.sources || []);
                          setActiveInspector(item.ragInspector || null);
                          setActiveMessageId(item.id);
                        }}
                      >
                        只看史料依据
                      </button>
                    </div>
                  )}
                </article>
              ))
            )}
              <div ref={chatBottomRef} aria-hidden="true" />
            </div>
          </div>

          {loading && (
            <div className="progress-card" aria-label="生成进度">
              {progressSteps.map((step, index) => (
                <div
                  className={`progress-step ${progressStep > index ? "done" : ""} ${progressStep === index ? "active" : ""} ${progressFailed && progressStep === index ? "failed" : ""}`}
                  key={step}
                >
                  <span>{index + 1}</span>
                  <p>{step}</p>
                </div>
              ))}
            </div>
          )}

          {agentSteps.length > 0 && !loading && (
            <div className="agent-steps-card" aria-label="Agent 执行步骤">
              <div className="agent-steps-header">
                <span className="agent-steps-icon">⚙️</span>
                <span>执行步骤</span>
              </div>
              <ul className="agent-steps-list">
                {agentSteps.map((step, index) => (
                  <li key={index} className="agent-step-item">
                    <span className="agent-step-bullet">•</span>
                    <span>{step}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {errorMessage && (
            <div className="error-card" role="alert">
              <strong>暂时无法生成回答</strong>
              <p>{errorMessage}</p>
              <ul>
                <li>检查后端服务是否正在运行。</li>
                <li>检查项目根目录 `.env.local` 是否已配置模型 Key。</li>
                <li>换一个人物或问题后重试。</li>
              </ul>
              <button className="secondary" type="button" disabled={loading} onClick={() => submit()}>重新生成</button>
            </div>
          )}

          {(status || copyStatus) && (
            <div className="status-row" aria-live="polite">
              {status && <span>{status}</span>}
              {copyStatus && <span>{copyStatus}</span>}
            </div>
          )}

          <form className="composer" onSubmit={submit}>
            <div className="composer-grid">
              <div>
                <label htmlFor="character">历史人物</label>
                <input id="character" value={character} onChange={(event) => handleCharacterChange(event.target.value)} />
                <div className="free-input-note">如果知识库中该人物资料较少，系统会基于已检索到的史料有限回答，请重点查看右侧史料依据。</div>
              </div>
              <div>
                <label htmlFor="message">学生问题</label>
                <textarea
                  id="message"
                  value={message}
                  maxLength={300}
                  onChange={(event) => setMessage(event.target.value)}
                  onKeyDown={(event: KeyboardEvent<HTMLTextAreaElement>) => {
                    if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !loading) {
                      event.preventDefault();
                      submit();
                    }
                  }}
                />
                <div className="input-help">
                  {message.length}/300
                  <span className="kbd-hint" style={{ marginLeft: 10 }}>
                    <kbd>Ctrl</kbd>+<kbd>↵</kbd> 发送
                  </span>
                </div>
              </div>
            </div>
            <button className="primary" type="submit" disabled={loading}>
              {loading ? "流式生成中..." : "开始对话"}
            </button>
          </form>
        </section>

        <aside className={`sources-panel panel workspace-panel-enter${activeMobilePanel !== "sources" ? " mobile-panel-hidden" : ""}`} aria-label="史料依据">
          <div className="panel-heading">
            <div>
              <span className="panel-kicker">史料证据</span>
              <h2>回答从哪里来</h2>
            </div>
            <button className="sources-panel-toggle" type="button" onClick={() => setSourcesOpen((v) => !v)}>
              {sourcesOpen ? "收起" : `展开${activeSources.length ? ` · ${activeSources.length} 条` : ""}`}
            </button>
          </div>

          {sourcesOpen && activeInspector && (
            <div className="rag-inspector-card">
              <div className="source-kicker">RAG Inspector</div>
              <strong>检索过程</strong>
              {activeInspector.original_question && <p>原问题：{activeInspector.original_question}</p>}
              {activeInspector.rewritten_query && <p>改写查询：{activeInspector.rewritten_query}</p>}
              <p>策略：{getRetrievalStrategyLabel(activeInspector.retrieval_strategy)} · {activeInspector.source_count ?? activeSources.length} 条片段</p>
              {activeInspector.expanded_queries?.length ? (
                <div className="learning-runtime-chips">
                  {activeInspector.expanded_queries.map((query) => <small key={query}>{query}</small>)}
                </div>
              ) : null}
            </div>
          )}

          {sourcesOpen && (
          <div className="verify-note">
            已通过史实一致性检查表示系统已根据检索史料做过一次校验，学习时仍建议结合教材理解。
          </div>
          )}

          {sourcesOpen && (
          <div className="sources">
            {activeSources.length > 0 ? (
              <>
                {visibleSources.map((source, index) => renderSourceCard(source, index))}
                {activeSources.length > 2 && (
                  <button className="secondary full" type="button" onClick={() => setShowAllSources((value) => !value)}>
                    {showAllSources ? "收起部分史料" : `展开更多史料（共 ${activeSources.length} 条）`}
                  </button>
                )}
              </>
            ) : (
              <div className="empty-state compact-empty">
                <span className="empty-stamp" aria-hidden="true">证</span>
                <strong>暂无史料依据</strong>
                <span>提交问题后，这里会展示 Agent 检索到的教材或原始史料。</span>
              </div>
            )}
          </div>
          )}
        </aside>
      </section>
    </main>
  );
}
