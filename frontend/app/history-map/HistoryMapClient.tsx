"use client";

import { useEffect, useState, useRef } from "react";
import { MapContainer, TileLayer, Marker, Popup, useMap } from "react-leaflet";
import { apiUrl } from "@/lib/api";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// 修复 Leaflet 默认图标问题
if (typeof window !== "undefined") {
  delete (L.Icon.Default.prototype as any)._getIconUrl;
  L.Icon.Default.mergeOptions({
    iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
    iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
    shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
  });
}

// 中国传统色
const CHINESE_COLORS = {
  朱砂: "#C0392B",
  石青: "#2C3E50",
  赭石: "#8B5A2B",
  藤黄: "#F39C12",
  黛绿: "#27AE60",
  紫檀: "#7F8C8D",
  靛蓝: "#1ABC9C",
  绛紫: "#9B59B6",
  墨色: "#34495E",
  铅白: "#95A5A6",
  赭红: "#D35400",
  翠绿: "#16A085",
};

const DYNASTIES = [
  { name: "史前", year: -2070, color: CHINESE_COLORS.紫檀, period: "远古-前2070" },
  { name: "夏", year: -1600, color: CHINESE_COLORS.赭石, period: "前2070-前1600" },
  { name: "商", year: -1046, color: CHINESE_COLORS.石青, period: "前1600-前1046" },
  { name: "周", year: -771, color: CHINESE_COLORS.黛绿, period: "前1046-前771" },
  { name: "春秋", year: -476, color: CHINESE_COLORS.翠绿, period: "前770-前476" },
  { name: "战国", year: -221, color: CHINESE_COLORS.赭石, period: "前475-前221" },
  { name: "秦", year: -206, color: CHINESE_COLORS.石青, period: "前221-前206" },
  { name: "汉", year: 220, color: CHINESE_COLORS.朱砂, period: "前202-220" },
  { name: "三国", year: 280, color: CHINESE_COLORS.赭红, period: "220-280" },
  { name: "晋", year: 420, color: CHINESE_COLORS.紫檀, period: "265-420" },
  { name: "南北朝", year: 589, color: CHINESE_COLORS.黛绿, period: "420-589" },
  { name: "隋", year: 618, color: CHINESE_COLORS.翠绿, period: "581-618" },
  { name: "唐", year: 907, color: CHINESE_COLORS.藤黄, period: "618-907" },
  { name: "宋", year: 1279, color: CHINESE_COLORS.绛紫, period: "960-1279" },
  { name: "元", year: 1368, color: CHINESE_COLORS.靛蓝, period: "1271-1368" },
  { name: "明", year: 1644, color: CHINESE_COLORS.朱砂, period: "1368-1644" },
  { name: "清", year: 1912, color: CHINESE_COLORS.墨色, period: "1636-1912" },
  { name: "民国", year: 1949, color: CHINESE_COLORS.铅白, period: "1912-1949" },
  { name: "新中国", year: 2024, color: CHINESE_COLORS.朱砂, period: "1949-至今" },
];

const TYPE_ICONS: Record<string, { emoji: string; color: string; label: string }> = {
  battle: { emoji: "⚔️", color: "#8B0000", label: "战役" },
  politics: { emoji: "🏛️", color: "#4A4A4A", label: "政治" },
  culture: { emoji: "📜", color: "#2F4F4F", label: "文化" },
  construction: { emoji: "🏗️", color: "#8B4513", label: "建设" },
  diplomacy: { emoji: "🤝", color: "#006400", label: "外交" },
};

function MapController({ center, zoom, isPanelOpen }: { center: [number, number]; zoom: number; isPanelOpen: boolean }) {
  const map = useMap();
  useEffect(() => {
    map.setView(center, zoom);
  }, [center, zoom, map]);
  useEffect(() => {
    setTimeout(() => map.invalidateSize(), 310);
  }, [isPanelOpen, map]);
  return null;
}

interface GeoEvent {
  id: string;
  title: string;
  year_start: number;
  dynasty: string;
  lat: number;
  lng: number;
  location_name: string;
  type: string;
  summary: string;
  character?: string;
}

export default function HistoryMapClient() {
  const [events, setEvents] = useState<GeoEvent[]>([]);
  const [selectedDynasty, setSelectedDynasty] = useState(DYNASTIES[0].name);
  const [selectedEvent, setSelectedEvent] = useState<GeoEvent | null>(null);
  const [narration, setNarration] = useState("");
  const [mapCenter, setMapCenter] = useState<[number, number]>([35.0, 105.0]);
  const [mapZoom, setMapZoom] = useState(4);
  const [relatedEventIds, setRelatedEventIds] = useState<string[]>([]);
  const [isPanelOpen, setIsPanelOpen] = useState(false);
  const [isAutoPlay, setIsAutoPlay] = useState(true);
  const [currentDynastyIndex, setCurrentDynastyIndex] = useState(0);
  const [chatInput, setChatInput] = useState("");
  const [chatResponse, setChatResponse] = useState("");

  const eventSourceRef = useRef<EventSource | null>(null);
  const autoPlayRef = useRef<NodeJS.Timeout | null>(null);
  const narrationRef = useRef("");

  const currentDynasty = DYNASTIES.find((d) => d.name === selectedDynasty);

  useEffect(() => {
    narrationRef.current = narration;
  }, [narration]);

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
    };
  }, []);

  // 自动播放时间轴
  useEffect(() => {
    if (isAutoPlay) {
      autoPlayRef.current = setInterval(() => {
        setCurrentDynastyIndex((prev) => {
          const next = (prev + 1) % DYNASTIES.length;
          setSelectedDynasty(DYNASTIES[next].name);
          return next;
        });
      }, 5000); // 每5秒切换一个朝代
    } else {
      if (autoPlayRef.current) {
        clearInterval(autoPlayRef.current);
      }
    }
    return () => {
      if (autoPlayRef.current) {
        clearInterval(autoPlayRef.current);
      }
    };
  }, [isAutoPlay]);

  // 同步当前朝代索引
  useEffect(() => {
    const idx = DYNASTIES.findIndex((d) => d.name === selectedDynasty);
    if (idx !== -1) {
      setCurrentDynastyIndex(idx);
    }
  }, [selectedDynasty]);

  useEffect(() => {
    fetchEvents(selectedDynasty);
  }, [selectedDynasty]);

  const fetchEvents = async (dynasty: string) => {
    try {
      const res = await fetch(apiUrl(`/api/history/geo/events?dynasty=${encodeURIComponent(dynasty)}`));
      const data = await res.json();
      setEvents(data.events || []);
    } catch {
      // keep existing events on fetch error
    }
  };

  const handleEventClick = (event: GeoEvent) => {
    setSelectedEvent(event);
    setNarration("");
    narrationRef.current = "";
    setRelatedEventIds([]);
    setMapCenter([event.lat, event.lng]);
    setMapZoom(6);
    setIsPanelOpen(true);
    setIsAutoPlay(false); // 点击事件时暂停自动播放

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const source = new EventSource(
      apiUrl(`/api/history/geo/narrate?event_id=${event.id}`)
    );
    eventSourceRef.current = source;

    source.onmessage = (e) => {
      const data = JSON.parse(e.data);
      if (data.event === "delta") {
        setNarration((prev) => {
          const next = prev + data.data.text;
          narrationRef.current = next;
          return next;
        });
      } else if (data.event === "final") {
        narrationRef.current = data.data.response;
        setNarration(data.data.response);
      } else if (data.event === "map_actions") {
        setRelatedEventIds(data.data.related_event_ids || []);
        if (data.data.actions?.[0]?.action === "fly_to") {
          const action = data.data.actions[0];
          setMapCenter([action.lat, action.lng]);
          setMapZoom(action.zoom || 6);
        }
      }
    };

    source.onerror = () => {
      if (!narrationRef.current) setNarration("加载失败，请点击其他事件重试。");
      source.close();
    };
  };

  const handleRelatedClick = (eventId: string) => {
    const event = events.find((e) => e.id === eventId);
    if (event) {
      handleEventClick(event);
    }
  };

  const toggleAutoPlay = () => {
    setIsAutoPlay(!isAutoPlay);
  };

  const handleChatSubmit = async (query: string) => {
    setChatResponse("正在思考...");
    setChatInput("");

    try {
      const res = await fetch(
        apiUrl(`/api/history/geo/chat?query=${encodeURIComponent(query)}`)
      );
      const data = await res.json();
      setChatResponse(data.response || "史官暂无回答");

      // 处理 map_actions
      if (data.map_actions) {
        if (data.map_actions.dynasty) {
          const idx = DYNASTIES.findIndex((d) => d.name === data.map_actions.dynasty);
          if (idx !== -1) {
            setSelectedDynasty(data.map_actions.dynasty);
            setCurrentDynastyIndex(idx);
          }
        }
        if (data.map_actions.event_id) {
          const event = events.find((e) => e.id === data.map_actions.event_id);
          if (event) {
            handleEventClick(event);
          }
        }
        if (data.map_actions.fly_to) {
          setMapCenter([data.map_actions.fly_to.lat, data.map_actions.fly_to.lng]);
          setMapZoom(data.map_actions.fly_to.zoom || 6);
        }
      }
    } catch {
      setChatResponse("史官暂时无法回答");
    }
  };

  return (
    <div
      style={{
        display: "flex",
        height: "100vh",
        width: "calc(100% + 48px)",
        margin: "-24px",
        overflow: "hidden",
        fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', 'SimSun', '宋体', serif",
        backgroundColor: "#F5F0E6",
        backgroundImage: `
          linear-gradient(rgba(245, 240, 230, 0.95), rgba(245, 240, 230, 0.95)),
          url("data:image/svg+xml,%3Csvg width='100' height='100' viewBox='0 0 100 100' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.08'/%3E%3C/svg%3E")
        `,
      }}
    >
      {/* 左侧地图 */}
      <div style={{ flex: 1, position: "relative", height: "100%" }}>
        <MapContainer
          center={mapCenter}
          zoom={mapZoom}
          style={{ height: "100%", width: "100%", zIndex: 1 }}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            className="map-tile-filter"
          />
          <MapController center={mapCenter} zoom={mapZoom} isPanelOpen={isPanelOpen} />
          {events.map((event) => {
            const typeInfo = TYPE_ICONS[event.type] || TYPE_ICONS.politics;
            return (
              <Marker
                key={event.id}
                position={[event.lat, event.lng]}
                eventHandlers={{
                  click: () => handleEventClick(event),
                }}
              >
                <Popup>
                  <div
                    style={{
                      padding: "16px",
                      minWidth: "220px",
                      fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                      backgroundColor: "#FAF7F2",
                      border: "2px solid #8B5A2B",
                      borderRadius: "4px",
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "10px",
                        marginBottom: "10px",
                        borderBottom: "1px solid #D4C5A9",
                        paddingBottom: "8px",
                      }}
                    >
                      <span style={{ fontSize: "24px" }}>{typeInfo.emoji}</span>
                      <div style={{ fontWeight: 600, fontSize: "16px", color: "#4A3728" }}>
                        {event.title}
                      </div>
                    </div>
                    <div style={{ fontSize: "14px", color: "#6B5D4F", marginBottom: "6px" }}>
                      {event.year_start < 0
                        ? `公元前${Math.abs(event.year_start)}年`
                        : `公元${event.year_start}年`}
                    </div>
                    <div style={{ fontSize: "13px", color: "#8B7D6B" }}>{event.location_name}</div>
                  </div>
                </Popup>
              </Marker>
            );
          })}
        </MapContainer>

        {/* 顶部标题栏 - 古风设计 */}
        <div
          style={{
            position: "absolute",
            top: "20px",
            left: "20px",
            right: "20px",
            backgroundColor: "rgba(250, 247, 242, 0.95)",
            backdropFilter: "blur(8px)",
            borderRadius: "8px",
            padding: "16px 24px",
            boxShadow: "0 4px 16px rgba(139, 90, 43, 0.15)",
            zIndex: 1000,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            border: "2px solid #D4C5A9",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
            <div>
              <h1
                style={{
                  fontSize: "24px",
                  fontWeight: 600,
                  margin: 0,
                  color: "#4A3728",
                  fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                  letterSpacing: "4px",
                }}
              >
                历史时空
              </h1>
              <p
                style={{
                  fontSize: "13px",
                  color: "#8B7D6B",
                  margin: "4px 0 0 0",
                  fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                }}
              >
                览千年风云，阅华夏春秋
              </p>
            </div>
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "12px",
              padding: "10px 20px",
              backgroundColor: currentDynasty?.color || "#8B5A2B",
              borderRadius: "4px",
              color: "#FAF7F2",
              fontSize: "16px",
              fontWeight: 500,
              fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
              border: "1px solid rgba(255,255,255,0.2)",
            }}
          >
            <span style={{ fontSize: "20px" }}>🏛️</span>
            <span>{currentDynasty?.name}</span>
            <span style={{ opacity: 0.8, fontSize: "13px" }}>· {currentDynasty?.period}</span>
          </div>
        </div>

        {/* 底部时间轴 - 刻度展示 */}
        <div
          style={{
            position: "absolute",
            bottom: "24px",
            left: "50%",
            transform: "translateX(-50%)",
            backgroundColor: "rgba(250, 247, 242, 0.95)",
            backdropFilter: "blur(8px)",
            borderRadius: "8px",
            padding: "20px 32px",
            boxShadow: "0 8px 24px rgba(139, 90, 43, 0.2)",
            zIndex: 1000,
            border: "2px solid #D4C5A9",
            width: "min(800px, calc(100% - 80px))",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "12px" }}>
            <button
              onClick={toggleAutoPlay}
              style={{
                padding: "8px 16px",
                border: "2px solid #8B5A2B",
                borderRadius: "4px",
                fontSize: "14px",
                fontWeight: 500,
                cursor: "pointer",
                backgroundColor: isAutoPlay ? "#8B5A2B" : "#FAF7F2",
                color: isAutoPlay ? "#FAF7F2" : "#8B5A2B",
                fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                transition: "all 0.3s",
              }}
            >
              {isAutoPlay ? "⏸ 暂停" : "▶ 播放"}
            </button>
            <div style={{ fontSize: "14px", color: "#8B7D6B", fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif" }}>
              {currentDynasty?.period}
            </div>
          </div>

          {/* 时间轴刻度 */}
          <div style={{ position: "relative", height: "60px", margin: "0 10px" }}>
            {/* 主轴线 */}
            <div
              style={{
                position: "absolute",
                top: "28px",
                left: "0",
                right: "0",
                height: "3px",
                backgroundColor: "#D4C5A9",
                borderRadius: "2px",
              }}
            />

            {/* 刻度和朝代 */}
            {DYNASTIES.map((d, idx) => {
              const left = (idx / (DYNASTIES.length - 1)) * 100;
              const isActive = idx === currentDynastyIndex;
              return (
                <div
                  key={d.name}
                  onClick={() => {
                    setSelectedDynasty(d.name);
                    setCurrentDynastyIndex(idx);
                  }}
                  style={{
                    position: "absolute",
                    left: `${left}%`,
                    top: 0,
                    transform: "translateX(-50%)",
                    cursor: "pointer",
                    transition: "all 0.3s",
                  }}
                >
                  {/* 刻度线 */}
                  <div
                    style={{
                      width: "2px",
                      height: isActive ? "36px" : "20px",
                      backgroundColor: isActive ? d.color : "#D4C5A9",
                      margin: "0 auto",
                      transition: "all 0.3s",
                    }}
                  />
                  {/* 朝代名称 */}
                  <div
                    style={{
                      marginTop: "8px",
                      fontSize: isActive ? "15px" : "13px",
                      fontWeight: isActive ? 600 : 400,
                      color: isActive ? d.color : "#8B7D6B",
                      fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                      textAlign: "center",
                      whiteSpace: "nowrap",
                      transition: "all 0.3s",
                    }}
                  >
                    {d.name}
                  </div>
                  {/* 年份 */}
                  <div
                    style={{
                      marginTop: "2px",
                      fontSize: "11px",
                      color: isActive ? d.color : "#A89F91",
                      fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                      textAlign: "center",
                    }}
                  >
                    {d.year < 0 ? `前${Math.abs(d.year)}` : d.year}
                  </div>
                </div>
              );
            })}

            {/* 游标 */}
            <div
              style={{
                position: "absolute",
                left: `${(currentDynastyIndex / (DYNASTIES.length - 1)) * 100}%`,
                top: "50%",
                transform: "translate(-50%, -50%)",
                width: "16px",
                height: "16px",
                backgroundColor: currentDynasty?.color || "#8B5A2B",
                borderRadius: "50%",
                border: "3px solid #FAF7F2",
                boxShadow: "0 2px 8px rgba(139, 90, 43, 0.4)",
                transition: "left 0.5s ease",
                zIndex: 10,
              }}
            />
          </div>
        </div>

        {/* 面板切换按钮 */}
        <button
          onClick={() => setIsPanelOpen(!isPanelOpen)}
          style={{
            position: "absolute",
            right: "12px",
            bottom: "unset",
            top: "50%",
            transform: "translateY(-50%)",
            zIndex: 1000,
            width: "36px",
            height: "36px",
            borderRadius: "50%",
            border: "1px solid #D4C5A9",
            backgroundColor: "rgba(250, 247, 242, 0.92)",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: "14px",
            color: "#8B7D6B",
            boxShadow: "0 2px 8px rgba(139, 90, 43, 0.12)",
          }}
        >
          {isPanelOpen ? "›" : "‹"}
        </button>
      </div>

      {/* 右侧事件面板 - 古风设计 */}
      <div
        style={{
          width: isPanelOpen ? "420px" : "0",
          flexShrink: 0,
          position: "relative",
          backgroundColor: "#FAF7F2",
          borderLeft: isPanelOpen ? "2px solid #D4C5A9" : "none",
          overflow: "hidden",
          transition: "width 0.3s ease",
          boxShadow: isPanelOpen ? "-4px 0 20px rgba(139, 90, 43, 0.1)" : "none",
          backgroundImage: `
            linear-gradient(rgba(250, 247, 242, 0.98), rgba(250, 247, 242, 0.98)),
            url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23D4C5A9' fill-opacity='0.15'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E")
          `,
        }}
      >
        <div style={{ width: "420px", height: "100%", overflowY: "auto" }}>
        {selectedEvent ? (
          <div style={{ padding: "28px" }}>
            <button
              onClick={() => setSelectedEvent(null)}
              style={{
                fontSize: "14px",
                color: "#8B7D6B",
                marginBottom: "20px",
                cursor: "pointer",
                background: "none",
                border: "none",
                display: "flex",
                alignItems: "center",
                gap: "6px",
                fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
              }}
            >
              <span>◀</span> 返回地图
            </button>

            {/* 事件标题 */}
            <div style={{ marginBottom: "24px", textAlign: "center" }}>
              <div
                style={{
                  display: "inline-block",
                  padding: "8px 20px",
                  backgroundColor: TYPE_ICONS[selectedEvent.type]?.color || "#8B5A2B",
                  color: "#FAF7F2",
                  borderRadius: "4px",
                  fontSize: "13px",
                  fontWeight: 500,
                  marginBottom: "16px",
                  fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                  border: "1px solid rgba(255,255,255,0.2)",
                }}
              >
                {TYPE_ICONS[selectedEvent.type]?.label || "事件"}
              </div>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "12px" }}>
                <span style={{ fontSize: "36px" }}>{TYPE_ICONS[selectedEvent.type]?.emoji || "📍"}</span>
                <h2
                  style={{
                    fontSize: "26px",
                    fontWeight: 600,
                    margin: 0,
                    color: "#4A3728",
                    fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                    letterSpacing: "2px",
                  }}
                >
                  {selectedEvent.title}
                </h2>
              </div>
            </div>

            {/* 时间地点信息 */}
            <div
              style={{
                backgroundColor: "#F5EDE0",
                borderRadius: "6px",
                padding: "20px",
                marginBottom: "24px",
                border: "1px solid #D4C5A9",
              }}
            >
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
                <div>
                  <div
                    style={{
                      fontSize: "13px",
                      color: "#8B7D6B",
                      marginBottom: "6px",
                      fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                    }}
                  >
                    时间
                  </div>
                  <div
                    style={{
                      fontSize: "16px",
                      fontWeight: 500,
                      color: "#4A3728",
                      fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                    }}
                  >
                    {selectedEvent.year_start < 0
                      ? `公元前${Math.abs(selectedEvent.year_start)}年`
                      : `公元${selectedEvent.year_start}年`}
                  </div>
                </div>
                <div>
                  <div
                    style={{
                      fontSize: "13px",
                      color: "#8B7D6B",
                      marginBottom: "6px",
                      fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                    }}
                  >
                    朝代
                  </div>
                  <div
                    style={{
                      fontSize: "16px",
                      fontWeight: 500,
                      color: "#4A3728",
                      fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                    }}
                  >
                    {selectedEvent.dynasty}
                  </div>
                </div>
                <div style={{ gridColumn: "span 2" }}>
                  <div
                    style={{
                      fontSize: "13px",
                      color: "#8B7D6B",
                      marginBottom: "6px",
                      fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                    }}
                  >
                    地点
                  </div>
                  <div
                    style={{
                      fontSize: "16px",
                      fontWeight: 500,
                      color: "#4A3728",
                      fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                    }}
                  >
                    {selectedEvent.location_name}
                  </div>
                </div>
              </div>
            </div>

            {/* 摘要 */}
            <div style={{ marginBottom: "28px" }}>
              <h3
                style={{
                  fontSize: "15px",
                  fontWeight: 600,
                  color: "#8B5A2B",
                  marginBottom: "12px",
                  fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                  letterSpacing: "2px",
                  borderBottom: "1px solid #D4C5A9",
                  paddingBottom: "8px",
                }}
              >
                事件概述
              </h3>
              <p
                style={{
                  fontSize: "15px",
                  color: "#4A3728",
                  lineHeight: "1.8",
                  margin: 0,
                  fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                  textIndent: "2em",
                }}
              >
                {selectedEvent.summary}
              </p>
            </div>

            {/* 相关人物 */}
            {selectedEvent.character && (
              <div style={{ marginBottom: "28px" }}>
                <h3
                  style={{
                    fontSize: "15px",
                    fontWeight: 600,
                    color: "#8B5A2B",
                    marginBottom: "12px",
                    fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                    letterSpacing: "2px",
                    borderBottom: "1px solid #D4C5A9",
                    paddingBottom: "8px",
                  }}
                >
                  相关人物
                </h3>
                <div
                  style={{
                    backgroundColor: "#F5EDE0",
                    padding: "14px 20px",
                    borderRadius: "6px",
                    display: "inline-block",
                    border: "1px solid #D4C5A9",
                  }}
                >
                  <span
                    style={{
                      fontSize: "16px",
                      fontWeight: 500,
                      color: "#4A3728",
                      fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                    }}
                  >
                    {selectedEvent.character}
                  </span>
                </div>
              </div>
            )}

            {/* AI 解说 */}
            <div style={{ marginBottom: "28px" }}>
              <h3
                style={{
                  fontSize: "15px",
                  fontWeight: 600,
                  color: "#8B5A2B",
                  marginBottom: "12px",
                  fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                  letterSpacing: "2px",
                  borderBottom: "1px solid #D4C5A9",
                  paddingBottom: "8px",
                }}
              >
                史官解说
              </h3>
              <div
                style={{
                  backgroundColor: "#F5EDE0",
                  borderRadius: "6px",
                  padding: "20px",
                  minHeight: "140px",
                  border: "1px solid #D4C5A9",
                  position: "relative",
                }}
              >
                <div
                  style={{
                    position: "absolute",
                    top: "8px",
                    left: "12px",
                    fontSize: "20px",
                    opacity: 0.3,
                  }}
                >
                  📜
                </div>
                <div
                  style={{
                    fontSize: "15px",
                    color: "#4A3728",
                    lineHeight: "1.8",
                    whiteSpace: "pre-wrap",
                    fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                    textIndent: "2em",
                  }}
                >
                  {narration || <span style={{ color: "#8B7D6B" }}>正在查阅史料...</span>}
                </div>
              </div>
            </div>

            {/* 相关事件 */}
            {relatedEventIds.length > 0 && (
              <div>
                <h3
                  style={{
                    fontSize: "15px",
                    fontWeight: 600,
                    color: "#8B5A2B",
                    marginBottom: "12px",
                    fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                    letterSpacing: "2px",
                    borderBottom: "1px solid #D4C5A9",
                    paddingBottom: "8px",
                  }}
                >
                  史海钩沉
                </h3>
                <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                  {relatedEventIds.map((id) => {
                    const relEvent = events.find((e) => e.id === id);
                    if (!relEvent) return null;
                    const typeInfo = TYPE_ICONS[relEvent.type] || TYPE_ICONS.politics;
                    return (
                      <button
                        key={id}
                        onClick={() => handleRelatedClick(id)}
                        style={{
                          width: "100%",
                          textAlign: "left",
                          padding: "14px 18px",
                          backgroundColor: "#F5EDE0",
                          cursor: "pointer",
                          borderRadius: "6px",
                          fontSize: "14px",
                          border: "1px solid #D4C5A9",
                          display: "flex",
                          alignItems: "center",
                          gap: "12px",
                          transition: "all 0.2s",
                          fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.backgroundColor = "#E8DFD0";
                          e.currentTarget.style.borderColor = "#8B5A2B";
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.backgroundColor = "#F5EDE0";
                          e.currentTarget.style.borderColor = "#D4C5A9";
                        }}
                      >
                        <span style={{ fontSize: "20px" }}>{typeInfo.emoji}</span>
                        <span style={{ fontWeight: 500, color: "#4A3728" }}>{relEvent.title}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* 对话输入框 */}
            <div style={{ marginTop: "28px", borderTop: "1px solid #D4C5A9", paddingTop: "20px" }}>
              <h3
                style={{
                  fontSize: "15px",
                  fontWeight: 600,
                  color: "#8B5A2B",
                  marginBottom: "12px",
                  fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                  letterSpacing: "2px",
                }}
              >
                史官问答
              </h3>
              <div
                style={{
                  backgroundColor: "#F5EDE0",
                  borderRadius: "6px",
                  padding: "16px",
                  border: "1px solid #D4C5A9",
                  marginBottom: "12px",
                  minHeight: "60px",
                }}
              >
                <div
                  style={{
                    fontSize: "14px",
                    color: "#4A3728",
                    lineHeight: "1.6",
                    fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                  }}
                >
                  {chatResponse || <span style={{ color: "#8B7D6B" }}>可与史官对话，如&ldquo;带我看唐朝的战役&rdquo;</span>}
                </div>
              </div>
              <div style={{ display: "flex", gap: "8px" }}>
                <input
                  type="text"
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  onKeyPress={(e) => {
                    if (e.key === "Enter" && chatInput.trim()) {
                      handleChatSubmit(chatInput);
                    }
                  }}
                  placeholder="输入问题..."
                  style={{
                    flex: 1,
                    padding: "10px 14px",
                    border: "1px solid #D4C5A9",
                    borderRadius: "4px",
                    fontSize: "14px",
                    fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                    backgroundColor: "#FAF7F2",
                    color: "#4A3728",
                    outline: "none",
                  }}
                />
                <button
                  onClick={() => chatInput.trim() && handleChatSubmit(chatInput)}
                  style={{
                    padding: "10px 20px",
                    border: "2px solid #8B5A2B",
                    borderRadius: "4px",
                    fontSize: "14px",
                    fontWeight: 500,
                    cursor: "pointer",
                    backgroundColor: "#8B5A2B",
                    color: "#FAF7F2",
                    fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                  }}
                >
                  发问
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div style={{ padding: "32px", textAlign: "center", color: "#8B7D6B" }}>
            <div style={{ fontSize: "56px", marginBottom: "20px" }}>🗺️</div>
            <p
              style={{
                fontSize: "18px",
                fontWeight: 500,
                marginBottom: "12px",
                color: "#4A3728",
                fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
                letterSpacing: "4px",
              }}
            >
              览千年风云
            </p>
            <p
              style={{
                fontSize: "14px",
                lineHeight: "1.8",
                fontFamily: "'Kaiti', 'STKaiti', 'KaiTi', '楷体', serif",
              }}
            >
              点击地图标记查看详情<br />
              时间轴自动循环播放
            </p>
          </div>
        )}
        </div>
      </div>
    </div>
  );
}
