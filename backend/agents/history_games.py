from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from random import choice, shuffle
from typing import Any, Literal, TypedDict
from uuid import uuid4

from agents.card_game import generate_card_game_round, generate_retry_explanation
from agents.timeline_question_generator import event_count_for_difficulty, generate_timeline_round_from_corpus, generate_timeline_round_with_llm
from game_store import (
    append_card_game_report, cleanup_expired_rounds, get_card_game_reports,
    get_wrong_records, load_round, save_round, save_wrong_records,
)
from services.weakpoint_service import record_weakpoint

GameStatus = Literal["available", "planned"]
TimelineDifficulty = Literal["easy", "normal", "hard"]


class HistoryGameDefinition(TypedDict):
    id: str
    title: str
    subtitle: str
    description: str
    teaching_goals: list[str]
    status: GameStatus
    estimated_minutes: int


class TimelineEventInternal(TypedDict):
    id: str
    title: str
    year: int
    display_year: str
    period: str
    summary: str
    topic: str
    explanation: str
    related_character: str | None
    suggested_question: str | None


class TimelineLevel(TypedDict):
    id: str
    title: str
    grade: str
    difficulty: TimelineDifficulty
    topic: str
    events: list[TimelineEventInternal]


class TimelineRoundRecord(TypedDict):
    round_id: str
    level_id: str
    title: str
    grade: str
    difficulty: TimelineDifficulty
    topic: str
    events: list[TimelineEventInternal]
    correct_order: list[str]
    created_at: datetime
    source: Literal["llm", "static"]
    fallback_used: bool
    generation_reason: str | None
    learning_goal: str | None
    student_id: str | None


class CardGameRoundRecord(TypedDict):
    round_id: str
    title: str
    grade: str
    difficulty: TimelineDifficulty
    topic: str
    cards: list[TimelineEventInternal]
    correct_order: list[str]
    created_at: datetime
    learning_goal: str | None
    retry_used: bool
    source: Literal["llm", "static"]
    fallback_used: bool
    generation_reason: str | None
    student_id: str | None


HISTORY_GAMES: list[HistoryGameDefinition] = [
    {
        "id": "multiplayer",
        "title": "时间巨轮",
        "subtitle": "与 AI 玩家轮流出牌，手牌最先清空者获胜",
        "description": "每轮出一张牌插入时间轴，放错罚摸一张，体验多人竞技玩法。",
        "teaching_goals": ["时间观念", "竞技对抗", "轮次策略"],
        "status": "available",
        "estimated_minutes": 8,
    },
    {
        "id": "character-deduction",
        "title": "历史人物身份推理",
        "subtitle": "根据线索猜出历史人物",
        "description": "通过人物言行、制度主张和历史贡献推断身份。",
        "teaching_goals": ["人物识记", "线索归纳", "史实判断"],
        "status": "planned",
        "estimated_minutes": 5,
    },
    {
        "id": "dynasty-sandbox",
        "title": "朝代经营小沙盘",
        "subtitle": "在政策选择中理解王朝兴衰",
        "description": "扮演统治者权衡农业、军事、赋税、思想和外交。",
        "teaching_goals": ["制度理解", "历史因果", "治理权衡"],
        "status": "planned",
        "estimated_minutes": 8,
    },
    {
        "id": "causal-chain",
        "title": "历史事件因果链拼图",
        "subtitle": "拼出原因、经过、结果与影响",
        "description": "把事件碎片复原为完整的历史解释链条。",
        "teaching_goals": ["因果分析", "历史解释", "材料组织"],
        "status": "planned",
        "estimated_minutes": 6,
    },
    {
        "id": "history-scene",
        "title": "穿越历史现场",
        "subtitle": "进入历史场景完成史料任务",
        "description": "在历史现场与人物对话、收集线索并完成任务。",
        "teaching_goals": ["情境理解", "史料阅读", "任务探究"],
        "status": "planned",
        "estimated_minutes": 10,
    },
    {
        "id": "history-debate",
        "title": "历史辩论赛",
        "subtitle": "用材料和论据表达历史观点",
        "description": "围绕历史评价选择立场、组织证据并接受点评。",
        "teaching_goals": ["材料分析", "观点表达", "历史评价"],
        "status": "planned",
        "estimated_minutes": 8,
    },
]

TIMELINE_LEVELS: list[TimelineLevel] = [
    {
        "id": "ancient-china-basic-01",
        "title": "中国古代史基础线索",
        "grade": "七年级上/下",
        "difficulty": "easy",
        "topic": "中国古代史",
        "events": [
            {
                "id": "shang-yang-reform",
                "title": "商鞅变法",
                "year": -356,
                "display_year": "公元前356年",
                "period": "战国时期",
                "summary": "秦孝公任用商鞅进行变法，推动秦国富国强兵。",
                "topic": "商鞅变法",
                "explanation": "商鞅变法发生在战国时期，早于秦统一六国，是秦国走向强盛的重要制度改革。",
                "related_character": "商鞅",
                "suggested_question": "你为什么要变法？",
            },
            {
                "id": "qin-unification",
                "title": "秦统一六国",
                "year": -221,
                "display_year": "公元前221年",
                "period": "秦朝",
                "summary": "秦王嬴政完成统一，建立秦朝。",
                "topic": "秦朝统一",
                "explanation": "秦统一六国发生在商鞅变法之后，标志着中国历史上第一个统一的多民族封建国家建立。",
                "related_character": "秦始皇",
                "suggested_question": "统一六国后为什么要统一文字和度量衡？",
            },
            {
                "id": "han-wudi-unification",
                "title": "汉武帝巩固大一统",
                "year": -141,
                "display_year": "公元前141年起",
                "period": "西汉",
                "summary": "汉武帝在政治、思想、经济和军事方面加强中央集权。",
                "topic": "汉武帝大一统",
                "explanation": "汉武帝巩固大一统属于西汉时期，晚于秦朝统一，体现中央集权制度的进一步发展。",
                "related_character": "汉武帝",
                "suggested_question": "推恩令有什么作用？",
            },
            {
                "id": "zhang-qian-western-regions",
                "title": "张骞出使西域",
                "year": -138,
                "display_year": "公元前138年起",
                "period": "西汉",
                "summary": "张骞出使西域，促进汉朝与西域的联系。",
                "topic": "张骞通西域",
                "explanation": "张骞出使西域发生在汉武帝时期，是汉朝了解西域、拓展交流的重要事件。",
                "related_character": "张骞",
                "suggested_question": "出使西域为什么重要？",
            },
            {
                "id": "silk-road",
                "title": "丝绸之路形成",
                "year": -130,
                "display_year": "西汉时期",
                "period": "西汉",
                "summary": "丝绸之路成为东西方经济文化交流的重要通道。",
                "topic": "丝绸之路",
                "explanation": "丝绸之路的形成与张骞出使西域密切相关，体现了汉朝与中外交流的扩大。",
                "related_character": "张骞",
                "suggested_question": "丝绸之路有什么作用？",
            },
            {
                "id": "hundred-schools",
                "title": "百家争鸣",
                "year": -500,
                "display_year": "春秋战国时期",
                "period": "春秋战国",
                "summary": "诸子百家兴起，儒、道、法、墨等学派展开思想论争。",
                "topic": "百家争鸣",
                "explanation": "百家争鸣发生在春秋战国时期，早于商鞅变法和秦统一，是中国历史上思想最为活跃的时代。",
                "related_character": "孔子",
                "suggested_question": "各学派的主张有什么不同？",
            },
            {
                "id": "changping-battle",
                "title": "长平之战",
                "year": -260,
                "display_year": "公元前260年",
                "period": "战国末期",
                "summary": "秦赵两国在长平展开决战，赵国大败，秦统一大势已定。",
                "topic": "长平之战",
                "explanation": "长平之战发生在商鞅变法之后、秦统一六国之前，是战国末期决定性的大战。",
                "related_character": "白起",
                "suggested_question": "长平之战对秦统一有什么影响？",
            },
            {
                "id": "han-founding",
                "title": "西汉建立",
                "year": -202,
                "display_year": "公元前202年",
                "period": "西汉初期",
                "summary": "刘邦击败项羽，建立汉朝，定都长安。",
                "topic": "西汉建立",
                "explanation": "西汉建立晚于秦统一六国，刘邦吸取秦朝���亡的教训，推行休养生息政策。",
                "related_character": "刘邦",
                "suggested_question": "汉朝初期为什么要休养生息？",
            },
            {
                "id": "paper-invention",
                "title": "蔡伦改进造纸术",
                "year": 105,
                "display_year": "公元105年",
                "period": "东汉",
                "summary": "蔡伦改进造纸工艺，使纸成为廉价易得的书写材料。",
                "topic": "造纸术",
                "explanation": "蔡伦改进造纸术发生在东汉时期，远晚于西汉，是中国四大发明之一，对文化传播影响深远。",
                "related_character": "蔡伦",
                "suggested_question": "造纸术对文化传播有什么意义？",
            },
            {
                "id": "yu-controls-floods",
                "title": "大禹治水",
                "year": -2200,
                "display_year": "传说时代",
                "period": "五帝时期末",
                "summary": "禹采用疏导方法治理洪水，获得部落联盟拥护。",
                "topic": "大禹治水",
                "explanation": "大禹治水传说连接尧舜禅让与夏朝建立，是早期国家形成的重要叙事。",
                "related_character": "大禹",
                "suggested_question": "大禹治水为什么受到后人推崇？",
            },
            {
                "id": "xia-dynasty-founded",
                "title": "夏朝建立",
                "year": -2070,
                "display_year": "约公元前2070年",
                "period": "夏朝",
                "summary": "禹建立夏朝，我国早期国家开始出现。",
                "topic": "夏朝建立",
                "explanation": "夏朝建立晚于大禹治水传说，标志早期国家形态出现。",
                "related_character": "禹",
                "suggested_question": "夏朝建立为什么被视为早期国家开端？",
            },
            {
                "id": "hereditary-system",
                "title": "世袭制代替禅让制",
                "year": -2060,
                "display_year": "夏朝初期",
                "period": "夏朝",
                "summary": "启继承禹的位置，王位世袭制逐渐形成。",
                "topic": "世袭制",
                "explanation": "世袭制出现在夏朝初期，晚于禅让传说，反映权力继承方式变化。",
                "related_character": "启",
                "suggested_question": "世袭制形成说明国家权力发生了什么变化？",
            },
            {
                "id": "shang-dynasty-founded",
                "title": "商朝建立",
                "year": -1600,
                "display_year": "约公元前1600年",
                "period": "商朝",
                "summary": "汤灭夏后建立商朝，商代青铜文明逐渐发展。",
                "topic": "商朝建立",
                "explanation": "商朝建立晚于夏朝，是中国早期国家发展的重要阶段。",
                "related_character": "汤",
                "suggested_question": "商朝与夏朝相比有哪些新发展？",
            },
            {
                "id": "pan-geng-moves-yin",
                "title": "盘庚迁殷",
                "year": -1300,
                "display_year": "约公元前1300年",
                "period": "商朝后期",
                "summary": "盘庚把都城迁到殷，商朝统治逐渐稳定。",
                "topic": "商朝统治",
                "explanation": "盘庚迁殷发生在商朝后期，晚于商朝建立，殷墟成为研究商代的重要遗址。",
                "related_character": "盘庚",
                "suggested_question": "盘庚迁殷为什么重要？",
            },
            {
                "id": "oracle-bone-script",
                "title": "甲骨文成熟",
                "year": -1250,
                "display_year": "商朝后期",
                "period": "商朝后期",
                "summary": "甲骨文是刻写在龟甲和兽骨上的文字，已具备汉字基本结构。",
                "topic": "甲骨文",
                "explanation": "甲骨文成熟于商朝后期，是研究商代历史和汉字起源的重要证据。",
                "related_character": None,
                "suggested_question": "甲骨文为什么是重要史料？",
            },
            {
                "id": "wu-wang-conquers-shang",
                "title": "武王伐纣",
                "year": -1046,
                "display_year": "公元前1046年",
                "period": "西周初年",
                "summary": "周武王在牧野之战中击败商纣王，商朝灭亡。",
                "topic": "武王伐纣",
                "explanation": "武王伐纣结束商朝，直接推动西周建立。",
                "related_character": "周武王",
                "suggested_question": "牧野之战为什么成为商周更替的关键？",
            },
            {
                "id": "western-zhou-founded",
                "title": "西周建立",
                "year": -1045,
                "display_year": "公元前1046年后",
                "period": "西周",
                "summary": "周武王建立西周，定都镐京。",
                "topic": "西周建立",
                "explanation": "西周建立紧接武王伐纣，是商周更替后的新王朝。",
                "related_character": "周武王",
                "suggested_question": "西周为什么要实行分封？",
            },
            {
                "id": "zhou-feudal-system",
                "title": "西周分封制推行",
                "year": -1040,
                "display_year": "西周初年",
                "period": "西周",
                "summary": "周王把土地和平民、奴隶分封给宗亲和功臣，形成诸侯体系。",
                "topic": "分封制",
                "explanation": "分封制推行于西周初年，有利于巩固周王朝对广阔区域的控制。",
                "related_character": "周公",
                "suggested_question": "分封制怎样巩固西周统治？",
            },
            {
                "id": "western-zhou-falls",
                "title": "西周灭亡",
                "year": -771,
                "display_year": "公元前771年",
                "period": "西周末年",
                "summary": "犬戎攻破镐京，西周灭亡。",
                "topic": "西周灭亡",
                "explanation": "西周灭亡晚于国人暴动，标志周王室权威进一步衰落。",
                "related_character": "周幽王",
                "suggested_question": "西周灭亡的原因有哪些？",
            },
            {
                "id": "eastern-zhou-founded",
                "title": "东周开始",
                "year": -770,
                "display_year": "公元前770年",
                "period": "东周",
                "summary": "周平王东迁洛邑，东周开始。",
                "topic": "东周开始",
                "explanation": "东周开始紧随西周灭亡，进入春秋战国时期。",
                "related_character": "周平王",
                "suggested_question": "东迁后周王室地位发生了什么变化？",
            },
            {
                "id": "qi-huan-hegemony",
                "title": "齐桓公称霸",
                "year": -651,
                "display_year": "公元前651年",
                "period": "春秋时期",
                "summary": "齐桓公任用管仲改革，成为春秋时期首位霸主。",
                "topic": "春秋争霸",
                "explanation": "齐桓公称霸发生在东周初期之后，反映周王室衰微和诸侯势力上升。",
                "related_character": "齐桓公",
                "suggested_question": "齐桓公为什么能成为霸主？",
            },
            {
                "id": "iron-plough-oxen",
                "title": "铁农具和牛耕推广",
                "year": -600,
                "display_year": "春秋时期",
                "period": "春秋时期",
                "summary": "铁制农具和牛耕使用提高了农业生产效率。",
                "topic": "生产力发展",
                "explanation": "铁农具和牛耕推广推动社会经济变化，为战国变法提供基础。",
                "related_character": None,
                "suggested_question": "生产工具进步会带来哪些社会变化？",
            },
            {
                "id": "laozi-thought",
                "title": "老子提出道家思想",
                "year": -570,
                "display_year": "春秋后期",
                "period": "春秋时期",
                "summary": "老子主张顺应自然、无为而治，是道家学派创始人。",
                "topic": "老子思想",
                "explanation": "老子生活于春秋后期，早于战国时期百家争鸣的全面展开。",
                "related_character": "老子",
                "suggested_question": "老子的无为而治是什么意思？",
            },
            {
                "id": "confucius-education",
                "title": "孔子兴办私学",
                "year": -520,
                "display_year": "春秋后期",
                "period": "春秋时期",
                "summary": "孔子创办私学，主张有教无类，发展儒家思想。",
                "topic": "孔子思想",
                "explanation": "孔子兴办私学与春秋后期社会变化相关，推动教育对象扩大。",
                "related_character": "孔子",
                "suggested_question": "有教无类体现了怎样的教育思想？",
            },
            {
                "id": "three-families-divide-jin",
                "title": "三家分晋",
                "year": -403,
                "display_year": "公元前403年",
                "period": "战国初年",
                "summary": "韩、赵、魏被承认为诸侯，战国七雄格局逐渐形成。",
                "topic": "战国七雄",
                "explanation": "三家分晋发生在春秋争霸之后，是进入战国格局的重要标志。",
                "related_character": None,
                "suggested_question": "三家分晋为什么标志局势变化？",
            },
            {
                "id": "dujiangyan-built",
                "title": "都江堰修建",
                "year": -256,
                "display_year": "公元前256年",
                "period": "战国时期",
                "summary": "李冰主持修建都江堰，使成都平原成为天府之国。",
                "topic": "都江堰",
                "explanation": "都江堰修建晚于商鞅变法，体现战国时期水利工程和经济发展。",
                "related_character": "李冰",
                "suggested_question": "都江堰为什么能长期发挥作用？",
            },
            {
                "id": "chen-sheng-uprising",
                "title": "陈胜吴广起义",
                "year": -209,
                "display_year": "公元前209年",
                "period": "秦末",
                "summary": "陈胜、吴广在大泽乡起义，反抗秦朝暴政。",
                "topic": "秦末农民起义",
                "explanation": "陈胜吴广起义发生在秦朝后期，是中国历史上第一次大规模农民起义。",
                "related_character": "陈胜",
                "suggested_question": "秦末农民起义为什么爆发？",
            },
            {
                "id": "qin-falls",
                "title": "秦朝灭亡",
                "year": -207,
                "display_year": "公元前207年",
                "period": "秦末",
                "summary": "秦朝在农民起义和反秦力量打击下灭亡。",
                "topic": "秦朝灭亡",
                "explanation": "秦朝灭亡晚于陈胜吴广起义，说明暴政削弱了统一王朝统治基础。",
                "related_character": "秦二世",
                "suggested_question": "秦朝为什么很快灭亡？",
            },
            {
                "id": "chu-han-contention",
                "title": "楚汉之争",
                "year": -206,
                "display_year": "公元前206年起",
                "period": "秦汉之际",
                "summary": "刘邦和项羽为争夺天下展开长期战争。",
                "topic": "楚汉之争",
                "explanation": "楚汉之争发生在秦朝灭亡之后，最终以刘邦胜利并建立汉朝告终。",
                "related_character": "刘邦",
                "suggested_question": "刘邦为什么能战胜项羽？",
            },
            {
                "id": "wenjing-rule",
                "title": "文景之治",
                "year": -180,
                "display_year": "西汉前期",
                "period": "西汉前期",
                "summary": "汉文帝、汉景帝推行休养生息政策，社会经济恢复发展。",
                "topic": "文景之治",
                "explanation": "文景之治发生在西汉建立后、汉武帝时期前，为大一统局面奠定基础。",
                "related_character": "汉文帝",
                "suggested_question": "休养生息政策为什么有利于恢复经济？",
            },
            {
                "id": "western-regions-protectorate",
                "title": "西域都护设置",
                "year": -60,
                "display_year": "公元前60年",
                "period": "西汉后期",
                "summary": "西汉设置西域都护，加强对西域地区的管理。",
                "topic": "西域都护",
                "explanation": "西域都护设置晚于张骞出使西域，标志西域正式纳入中央政权管辖范围。",
                "related_character": None,
                "suggested_question": "西域都护的设置有什么意义？",
            },
            {
                "id": "eastern-han-founded",
                "title": "东汉建立",
                "year": 25,
                "display_year": "公元25年",
                "period": "东汉",
                "summary": "刘秀建立东汉，定都洛阳。",
                "topic": "东汉建立",
                "explanation": "东汉建立晚于王莽新朝，是汉朝统治的延续和重建。",
                "related_character": "刘秀",
                "suggested_question": "东汉为什么又称后汉？",
            },
            {
                "id": "buddhism-spreads-china",
                "title": "佛教传入中国",
                "year": 67,
                "display_year": "东汉时期",
                "period": "东汉",
                "summary": "佛教经丝绸之路等途径传入中国，并逐渐传播。",
                "topic": "文化交流",
                "explanation": "佛教传入中国发生在东汉时期，是中外文化交流的重要表现。",
                "related_character": None,
                "suggested_question": "佛教传入与丝绸之路有什么关系？",
            },
            {
                "id": "zhang-zhongjing-treatise",
                "title": "张仲景著成医书",
                "year": 200,
                "display_year": "东汉末年",
                "period": "东汉末年",
                "summary": "张仲景写成《伤寒杂病论》，总结中医临床经验。",
                "topic": "医学成就",
                "explanation": "张仲景医学成就出现在东汉末年，晚于蔡伦改进造纸术。",
                "related_character": "张仲景",
                "suggested_question": "张仲景为什么被称为医圣？",
            },
            {
                "id": "hua-tuo-medicine",
                "title": "华佗行医",
                "year": 208,
                "display_year": "东汉末年",
                "period": "东汉末年",
                "summary": "华佗擅长外科手术，创编五禽戏。",
                "topic": "医学成就",
                "explanation": "华佗活跃于东汉末年，与张仲景共同代表汉代医学发展。",
                "related_character": "华佗",
                "suggested_question": "五禽戏体现了怎样的养生思想？",
            },
            {
                "id": "yellow-turban-uprising",
                "title": "黄巾起义",
                "year": 184,
                "display_year": "公元184年",
                "period": "东汉末年",
                "summary": "张角领导黄巾起义，东汉统治受到沉重打击。",
                "topic": "东汉衰亡",
                "explanation": "黄巾起义发生在东汉末年，推动地方割据和三国局面形成。",
                "related_character": "张角",
                "suggested_question": "黄巾起义为什么会爆发？",
            },
            {
                "id": "sima-qian-shiji",
                "title": "司马迁写成《史记》",
                "year": -91,
                "display_year": "西汉时期",
                "period": "西汉",
                "summary": "司马迁撰写《史记》，开创纪传体通史体例。",
                "topic": "史学成就",
                "explanation": "《史记》成书于西汉时期，晚于汉武帝巩固大一统，是重要史学成果。",
                "related_character": "司马迁",
                "suggested_question": "《史记》为什么被称为纪传体通史？",
            },
            {
                "id": "battle-red-cliffs",
                "title": "赤壁之战",
                "year": 208,
                "display_year": "公元208年",
                "period": "东汉末年",
                "summary": "孙刘联军在赤壁击败曹操，奠定三国鼎立基础。",
                "topic": "三国鼎立",
                "explanation": "赤壁之战发生在东汉末年，晚于黄巾起义，是三国格局形成的关键。",
                "related_character": "曹操",
                "suggested_question": "赤壁之战为什么影响三国格局？",
            },
            {
                "id": "wei-kingdom-founded",
                "title": "魏国建立",
                "year": 220,
                "display_year": "公元220年",
                "period": "三国时期",
                "summary": "曹丕称帝，建立魏国，东汉结束。",
                "topic": "三国鼎立",
                "explanation": "魏国建立晚于赤壁之战，标志东汉正式结束。",
                "related_character": "曹丕",
                "suggested_question": "魏国建立说明东汉政权发生了什么变化？",
            },
            {
                "id": "shu-kingdom-founded",
                "title": "蜀汉建立",
                "year": 221,
                "display_year": "公元221年",
                "period": "三国时期",
                "summary": "刘备在成都称帝，建立蜀汉。",
                "topic": "三国鼎立",
                "explanation": "蜀汉建立紧随魏国建立，是三国鼎立格局的重要组成部分。",
                "related_character": "刘备",
                "suggested_question": "蜀汉为什么以成都为都城？",
            },
            {
                "id": "wu-kingdom-founded",
                "title": "吴国建立",
                "year": 229,
                "display_year": "公元229年",
                "period": "三国时期",
                "summary": "孙权称帝，吴国建立，三国鼎立局面正式形成。",
                "topic": "三国鼎立",
                "explanation": "吴国建立晚于魏、蜀建立，三国鼎立格局最终形成。",
                "related_character": "孙权",
                "suggested_question": "三国鼎立局面如何形成？",
            },
            {
                "id": "western-jin-unifies",
                "title": "西晋统一全国",
                "year": 280,
                "display_year": "公元280年",
                "period": "西晋",
                "summary": "西晋灭吴，结束三国鼎立局面，实现短暂统一。",
                "topic": "西晋统一",
                "explanation": "西晋统一晚于三国鼎立，是魏晋南北朝时期前的重要转折。",
                "related_character": "司马炎",
                "suggested_question": "西晋统一为什么被称为短暂统一？",
            },
            {
                "id": "eight-princes-war",
                "title": "八王之乱",
                "year": 291,
                "display_year": "公元291年起",
                "period": "西晋",
                "summary": "西晋宗室诸王争夺权力，导致统治严重削弱。",
                "topic": "西晋衰亡",
                "explanation": "八王之乱发生在西晋统一后，削弱西晋并加剧社会动荡。",
                "related_character": None,
                "suggested_question": "八王之乱为什么会削弱西晋？",
            },
            {
                "id": "eastern-jin-founded",
                "title": "东晋建立",
                "year": 317,
                "display_year": "公元317年",
                "period": "东晋",
                "summary": "司马睿在建康建立东晋，南方政权延续。",
                "topic": "东晋建立",
                "explanation": "东晋建立晚于西晋动荡，开启南方政权与北方民族政权并立局面。",
                "related_character": "司马睿",
                "suggested_question": "东晋为什么定都建康？",
            },
            {
                "id": "former-qin-unifies-north",
                "title": "前秦统一北方",
                "year": 376,
                "display_year": "公元376年",
                "period": "十六国时期",
                "summary": "前秦在苻坚统治下统一北方，南北对峙加剧。",
                "topic": "北方民族政权",
                "explanation": "前秦统一北方晚于东晋建立，为淝水之战埋下背景。",
                "related_character": "苻坚",
                "suggested_question": "前秦统一北方后为什么南下？",
            },
            {
                "id": "feishui-battle",
                "title": "淝水之战",
                "year": 383,
                "display_year": "公元383年",
                "period": "东晋时期",
                "summary": "东晋以少胜多击败前秦，南方政权得以稳定。",
                "topic": "淝水之战",
                "explanation": "淝水之战发生在前秦统一北方后，阻止了前秦南下统一。",
                "related_character": "谢安",
                "suggested_question": "淝水之战为什么能以少胜多？",
            },
            {
                "id": "liu-song-founded",
                "title": "刘宋建立",
                "year": 420,
                "display_year": "公元420年",
                "period": "南朝",
                "summary": "刘裕建立宋，南朝开始。",
                "topic": "南朝政权",
                "explanation": "刘宋建立晚于东晋，标志南朝宋齐梁陈相继更替的开始。",
                "related_character": "刘裕",
                "suggested_question": "南朝政权主要活动在哪一区域？",
            },
            {
                "id": "northern-wei-unifies-north",
                "title": "北魏统一北方",
                "year": 439,
                "display_year": "公元439年",
                "period": "北朝",
                "summary": "北魏统一北方，结束北方长期分裂局面。",
                "topic": "北魏统一",
                "explanation": "北魏统一北方晚于刘宋建立，形成南北朝对峙格局。",
                "related_character": "拓跋焘",
                "suggested_question": "北魏统一北方对民族交融有什么影响？",
            },
            {
                "id": "xiaowen-reform",
                "title": "北魏孝文帝改革",
                "year": 494,
                "display_year": "公元494年起",
                "period": "北魏",
                "summary": "孝文帝迁都洛阳，推行汉化措施，促进民族交融。",
                "topic": "孝文帝改革",
                "explanation": "孝文帝改革发生在北魏统一北方后，推动北方民族交融。",
                "related_character": "孝文帝",
                "suggested_question": "孝文帝改革为什么促进民族交融？",
            },
        ],
    },
    {
        "id": "modern-china-basic-01",
        "title": "中国近代史基础线索",
        "grade": "八年级上",
        "difficulty": "normal",
        "topic": "中国近代史",
        "events": [
            {
                "id": "opium-war",
                "title": "鸦片战争爆发",
                "year": 1840,
                "display_year": "1840年",
                "period": "晚清",
                "summary": "英国发动鸦片战争，中国开始沦为半殖民地半封建社会。",
                "topic": "鸦片战争",
                "explanation": "鸦片战争是中国近代史的开端，早于后来的洋务运动、戊戌变法和辛亥革命。",
                "related_character": "林则徐",
                "suggested_question": "虎门销烟有什么历史意义？",
            },
            {
                "id": "taiping-heavenly-kingdom",
                "title": "太平天国运动兴起",
                "year": 1851,
                "display_year": "1851年",
                "period": "晚清",
                "summary": "洪秀全发动金田起义，太平天国运动兴起。",
                "topic": "太平天国",
                "explanation": "太平天国运动发生在鸦片战争之后，反映了晚清社会矛盾的激化。",
                "related_character": "洪秀全",
                "suggested_question": "太平天国运动为什么会爆发？",
            },
            {
                "id": "self-strengthening-movement",
                "title": "洋务运动兴起",
                "year": 1861,
                "display_year": "19世纪60年代起",
                "period": "晚清",
                "summary": "清政府内部洋务派主张学习西方先进技术以自强求富。",
                "topic": "洋务运动",
                "explanation": "洋务运动兴起于19世纪60年代，晚于太平天国运动兴起，体现晚清自救探索。",
                "related_character": "李鸿章",
                "suggested_question": "洋务运动为什么要兴办近代工业？",
            },
            {
                "id": "hundred-days-reform",
                "title": "戊戌变法",
                "year": 1898,
                "display_year": "1898年",
                "period": "晚清",
                "summary": "维新派推动制度变革，希望通过变法救亡图存。",
                "topic": "戊戌变法",
                "explanation": "戊戌变法发生在洋务运动之后，探索从制度层面推动近代化。",
                "related_character": "康有为",
                "suggested_question": "戊戌变法为什么失败？",
            },
            {
                "id": "xinhai-revolution",
                "title": "辛亥革命",
                "year": 1911,
                "display_year": "1911年",
                "period": "近代中国",
                "summary": "辛亥革命推翻清朝统治，结束两千多年君主专制制度。",
                "topic": "辛亥革命",
                "explanation": "辛亥革命晚于戊戌变法，是近代中国民主革命的重要里程碑。",
                "related_character": "孙中山",
                "suggested_question": "辛亥革命有什么历史意义？",
            },
        ],
    },
    {
        "id": "world-history-basic-01",
        "title": "世界史基础线索",
        "grade": "九年级上/下",
        "difficulty": "normal",
        "topic": "世界史",
        "events": [
            {
                "id": "renaissance",
                "title": "文艺复兴兴起",
                "year": 1400,
                "display_year": "14世纪中叶起",
                "period": "世界近代史前期",
                "summary": "文艺复兴宣扬人文主义，推动欧洲思想文化发展。",
                "topic": "文艺复兴",
                "explanation": "文艺复兴早于新航路开辟，为欧洲近代社会转型提供思想文化条件。",
                "related_character": None,
                "suggested_question": None,
            },
            {
                "id": "new-route-opening",
                "title": "新航路开辟",
                "year": 1492,
                "display_year": "15世纪末起",
                "period": "世界近代史前期",
                "summary": "欧洲航海家开辟通往亚洲、美洲等地的新航路。",
                "topic": "新航路开辟",
                "explanation": "新航路开辟晚于文艺复兴兴起，促进世界开始连成一个整体。",
                "related_character": None,
                "suggested_question": None,
            },
            {
                "id": "english-bourgeois-revolution",
                "title": "英国资产阶级革命",
                "year": 1640,
                "display_year": "1640年起",
                "period": "世界近代史",
                "summary": "英国资产阶级革命推动君主立宪制逐步确立。",
                "topic": "英国资产阶级革命",
                "explanation": "英国资产阶级革命发生在新航路开辟之后，是资本主义制度确立的重要事件。",
                "related_character": None,
                "suggested_question": None,
            },
            {
                "id": "american-war-independence",
                "title": "美国独立战争",
                "year": 1775,
                "display_year": "1775年起",
                "period": "世界近代史",
                "summary": "北美殖民地反抗英国殖民统治，最终建立美国。",
                "topic": "美国独立战争",
                "explanation": "美国独立战争晚于英国资产阶级革命，也是资产阶级革命时代的重要事件。",
                "related_character": None,
                "suggested_question": None,
            },
            {
                "id": "industrial-revolution",
                "title": "第一次工业革命",
                "year": 1765,
                "display_year": "18世纪60年代起",
                "period": "世界近代史",
                "summary": "工业革命以机器生产代替手工劳动，极大提高社会生产力。",
                "topic": "工业革命",
                "explanation": "第一次工业革命开始于18世纪60年代，时间上略早于美国独立战争爆发，推动资本主义经济迅速发展。",
                "related_character": None,
                "suggested_question": None,
            },
        ],
    },
]

TIMELINE_RECENT_EVENTS: dict[str, list[str]] = {}
CARD_GAME_RECENT_EVENTS: dict[str, list[str]] = {}
logger = logging.getLogger(__name__)


def list_history_games() -> list[HistoryGameDefinition]:
    return HISTORY_GAMES


def start_timeline_round(
    grade: str | None = None,
    difficulty: str = "easy",
    topic: str | None = None,
    student_id: str | None = None,
    mode: str = "llm",
) -> dict:
    cleanup_expired_rounds()
    normalized_difficulty = normalize_difficulty(difficulty)
    normalized_mode = (mode or "llm").strip().lower()
    if normalized_mode not in {"llm", "static"}:
        raise ValueError("不支持的时间线出题模式，请选择 llm 或 static。")

    if normalized_mode == "static":
        return create_static_timeline_round(grade, normalized_difficulty, topic, student_id, fallback_used=False, generation_reason="mode=static")

    try:
        generated_round = generate_timeline_round_from_corpus(
            grade=grade,
            difficulty=normalized_difficulty,
            topic=topic,
            student_id=student_id,
            recent_store=TIMELINE_RECENT_EVENTS,
        )
        return create_timeline_round_record(
            level_id="llm-dynamic",
            title=generated_round["title"],
            grade=generated_round["grade"],
            difficulty=normalized_difficulty,
            topic=generated_round["topic"],
            events=generated_round["events"],
            source="llm",
            fallback_used=False,
            generation_reason=None,
            learning_goal=generated_round.get("learning_goal"),
            student_id=student_id,
        )
    except Exception as exc:
        logger.warning(
            "timeline_round_fallback difficulty=%s topic=%s reason=%s",
            normalized_difficulty,
            topic,
            str(exc),
        )
        return create_static_timeline_round(grade, normalized_difficulty, topic, student_id, fallback_used=True, generation_reason=str(exc))


def create_static_timeline_round(
    grade: str | None,
    difficulty: TimelineDifficulty,
    topic: str | None,
    student_id: str | None,
    fallback_used: bool,
    generation_reason: str | None,
) -> dict:
    level = choose_level(grade, difficulty, topic)
    return create_timeline_round_record(
        level_id=level["id"],
        title=level["title"],
        grade=level["grade"],
        difficulty=level["difficulty"],
        topic=level["topic"],
        events=[event.copy() for event in level["events"]],
        source="static",
        fallback_used=fallback_used,
        generation_reason=generation_reason,
        learning_goal=None,
        student_id=student_id,
    )


def create_timeline_round_record(
    *,
    level_id: str,
    title: str,
    grade: str,
    difficulty: TimelineDifficulty,
    topic: str,
    events: list[TimelineEventInternal] | list[dict[str, Any]],
    source: Literal["llm", "static"],
    fallback_used: bool,
    generation_reason: str | None,
    learning_goal: str | None,
    student_id: str | None,
) -> dict:
    round_events = [event.copy() for event in events]
    correct_order = [event["id"] for event in sorted(round_events, key=lambda item: item["year"])]
    shuffled_events = round_events.copy()
    shuffle(shuffled_events)
    if [event["id"] for event in shuffled_events] == correct_order and len(shuffled_events) > 1:
        shuffled_events[0], shuffled_events[1] = shuffled_events[1], shuffled_events[0]

    round_id = f"timeline-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid4().hex[:8]}"
    record: TimelineRoundRecord = {
        "round_id": round_id,
        "level_id": level_id,
        "title": title,
        "grade": grade,
        "difficulty": difficulty,
        "topic": topic,
        "events": round_events,  # type: ignore[typeddict-item]
        "correct_order": correct_order,
        "created_at": datetime.now(timezone.utc),
        "source": source,
        "fallback_used": fallback_used,
        "generation_reason": generation_reason,
        "learning_goal": learning_goal,
        "student_id": student_id,
    }
    save_round(round_id, "timeline", record)

    return {
        "round_id": round_id,
        "title": title,
        "round_title": title,
        "learning_goal": learning_goal,
        "grade": grade,
        "difficulty": difficulty,
        "topic": topic,
        "events": [public_event(event) for event in shuffled_events],
        "source": source,
        "fallback_used": fallback_used,
    }


def submit_timeline_round(round_id: str, ordered_event_ids: list[str]) -> dict:
    cleanup_expired_rounds()
    record = load_round(round_id)
    if not record:
        raise LookupError("时间线回合不存在或已过期，请重新开始一局。")

    correct_order = record["correct_order"]
    validate_submission(correct_order, ordered_event_ids)

    events_by_id = {event["id"]: event for event in record["events"]}
    correct_index_by_id = {event_id: index for index, event_id in enumerate(correct_order)}
    submitted_index_by_id = {event_id: index for index, event_id in enumerate(ordered_event_ids)}
    score = sum(
        1 for index, event_id in enumerate(ordered_event_ids)
        if correct_order[index] == event_id
    )

    items = []
    for event_id in ordered_event_ids:
        event = events_by_id[event_id]
        correct_index = correct_index_by_id[event_id]
        submitted_index = submitted_index_by_id[event_id]
        is_correct = correct_index == submitted_index
        items.append({
            "event_id": event_id,
            "title": event["title"],
            "display_year": event["display_year"],
            "period": event["period"],
            "is_correct_position": is_correct,
            "correct_index": correct_index,
            "submitted_index": submitted_index,
            "explanation": event["explanation"],
            "related_character": event["related_character"],
            "suggested_question": event["suggested_question"],
        })
        if not is_correct and record.get("student_id"):
            record_weakpoint(record["student_id"], event.get("topic", event["title"]), "timeline_game")

    return {
        "round_id": round_id,
        "score": score,
        "total": len(correct_order),
        "correct_order": correct_order,
        "submitted_order": ordered_event_ids,
        "items": items,
        "learning_tip": build_learning_tip(score, len(correct_order), record),
        "source": record["source"],
        "fallback_used": record["fallback_used"],
        "grade": record["grade"],
        "topic": record["topic"],
        "difficulty": record["difficulty"],
        "student_id": record.get("student_id"),
    }


def start_card_game_round(
    grade: str | None = None,
    difficulty: str = "easy",
    topic: str | None = None,
    student_id: str | None = None,
    mode: str = "llm",
) -> dict:
    cleanup_expired_rounds()
    normalized_difficulty = normalize_difficulty(difficulty)
    normalized_mode = (mode or "llm").strip().lower()
    if normalized_mode not in {"llm", "static"}:
        raise ValueError("不支持的卡牌游戏出题模式，请选择 llm 或 static。")

    wrong_card_ids = get_wrong_records(student_key(student_id))
    if normalized_mode == "static":
        return create_static_card_game_round(
            grade,
            normalized_difficulty,
            topic,
            student_id,
            fallback_used=False,
            generation_reason="mode=static",
        )

    try:
        generated_round = generate_card_game_round(
            levels=TIMELINE_LEVELS,  # type: ignore[arg-type]
            grade=grade,
            difficulty=normalized_difficulty,
            topic=topic,
            student_id=student_id,
            recent_store=CARD_GAME_RECENT_EVENTS,
            wrong_card_ids=wrong_card_ids,
        )
        return create_card_game_round_record(
            title=generated_round["title"],
            grade=generated_round["grade"],
            difficulty=normalized_difficulty,
            topic=generated_round["topic"],
            cards=generated_round["events"],
            source="llm",
            fallback_used=False,
            generation_reason=None,
            learning_goal=generated_round.get("learning_goal"),
            student_id=student_id,
        )
    except Exception as exc:
        logger.warning(
            "card_game_round_fallback difficulty=%s topic=%s reason=%s",
            normalized_difficulty,
            topic,
            str(exc),
        )
        return create_static_card_game_round(
            grade,
            normalized_difficulty,
            topic,
            student_id,
            fallback_used=True,
            generation_reason=str(exc),
        )


def create_static_card_game_round(
    grade: str | None,
    difficulty: TimelineDifficulty,
    topic: str | None,
    student_id: str | None,
    fallback_used: bool,
    generation_reason: str | None,
) -> dict:
    level = choose_level(grade, difficulty, topic)
    target_count = event_count_for_difficulty(difficulty)
    cards = [event.copy() for event in level["events"][:target_count]]
    return create_card_game_round_record(
        title=f"{level['title']} · 时间巨轮",
        grade=level["grade"],
        difficulty=difficulty,
        topic=level["topic"],
        cards=cards,
        source="static",
        fallback_used=fallback_used,
        generation_reason=generation_reason,
        learning_goal="根据卡牌线索判断事件先后，训练历史时间观念。",
        student_id=student_id,
    )


def create_card_game_round_record(
    *,
    title: str,
    grade: str,
    difficulty: TimelineDifficulty,
    topic: str,
    cards: list[TimelineEventInternal] | list[dict[str, Any]],
    source: Literal["llm", "static"],
    fallback_used: bool,
    generation_reason: str | None,
    learning_goal: str | None,
    student_id: str | None,
) -> dict:
    round_cards = [card.copy() for card in cards]
    correct_order = [card["id"] for card in sorted(round_cards, key=lambda item: item["year"])]
    shuffled_cards = round_cards.copy()
    shuffle(shuffled_cards)
    if [card["id"] for card in shuffled_cards] == correct_order and len(shuffled_cards) > 1:
        shuffled_cards[0], shuffled_cards[1] = shuffled_cards[1], shuffled_cards[0]

    round_id = f"card-game-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid4().hex[:8]}"
    record: CardGameRoundRecord = {
        "round_id": round_id,
        "title": title,
        "grade": grade,
        "difficulty": difficulty,
        "topic": topic,
        "cards": round_cards,  # type: ignore[typeddict-item]
        "correct_order": correct_order,
        "created_at": datetime.now(timezone.utc),
        "learning_goal": learning_goal,
        "retry_used": False,
        "source": source,
        "fallback_used": fallback_used,
        "generation_reason": generation_reason,
        "student_id": student_id,
    }
    save_round(round_id, "card_game", record)

    return {
        "round_id": round_id,
        "title": title,
        "learning_goal": learning_goal,
        "grade": grade,
        "topic": topic,
        "difficulty": difficulty,
        "cards": [public_card(card) for card in shuffled_cards],
        "slot_count": len(shuffled_cards),
        "source": source,
        "fallback_used": fallback_used,
    }


def submit_card_game_round(round_id: str, submitted_card_ids: list[str]) -> dict:
    cleanup_expired_rounds()
    record = load_round(round_id)
    if not record:
        raise LookupError("卡牌游戏回合不存在或已过期，请重新开始一局。")

    result = build_card_game_result(record, submitted_card_ids, can_retry=not record["retry_used"])
    persist_card_game_result(record, result, is_retry=False)
    return result


def retry_card_game_round(round_id: str, revised_card_ids: list[str]) -> dict:
    cleanup_expired_rounds()
    record = load_round(round_id)
    if not record:
        raise LookupError("卡牌游戏回合不存在或已过期，请重新开始一局。")
    if record["retry_used"]:
        raise ValueError("本局修正机会已经使用，请开启下一局。")

    record["retry_used"] = True
    save_round(record["round_id"], "card_game", record)
    result = build_card_game_result(record, revised_card_ids, can_retry=False)
    wrong_items = [item for item in result["items"] if not item["is_correct"]]
    retry_explanations = generate_retry_explanation(wrong_items, f"{record['title']} / {record['topic']}")
    for item in result["items"]:
        if item["card_id"] in retry_explanations:
            item["explanation"] = retry_explanations[item["card_id"]]
    persist_card_game_result(record, result, is_retry=True)
    return result


def build_card_game_result(record: CardGameRoundRecord, submitted_card_ids: list[str], can_retry: bool) -> dict:
    correct_order = record["correct_order"]
    validate_submission(correct_order, submitted_card_ids)

    cards_by_id = {card["id"]: card for card in record["cards"]}
    correct_index_by_id = {card_id: index for index, card_id in enumerate(correct_order)}
    submitted_index_by_id = {card_id: index for index, card_id in enumerate(submitted_card_ids)}
    score = sum(1 for index, card_id in enumerate(submitted_card_ids) if correct_order[index] == card_id)

    items = []
    for card_id in submitted_card_ids:
        card = cards_by_id[card_id]
        correct_index = correct_index_by_id[card_id]
        submitted_index = submitted_index_by_id[card_id]
        is_correct = correct_index == submitted_index
        items.append(
            {
                "card_id": card_id,
                "title": card["title"],
                "display_year": card["display_year"],
                "period": card["period"],
                "is_correct": is_correct,
                "correct_slot": correct_index,
                "submitted_slot": submitted_index,
                "explanation": card["explanation"],
                "follow_up_question": card["suggested_question"],
            }
        )
        if not is_correct and record.get("student_id"):
            record_weakpoint(record["student_id"], card.get("topic", card["title"]), "card_game")

    return {
        "round_id": record["round_id"],
        "score": score,
        "total": len(correct_order),
        "can_retry": can_retry,
        "items": items,
        "learning_tip": build_card_game_learning_tip(score, len(correct_order), record),
        "correct_order": correct_order,
        "submitted_order": submitted_card_ids,
        "student_id": record.get("student_id"),
        "grade": record.get("grade"),
        "topic": record.get("topic"),
        "difficulty": record.get("difficulty"),
    }


def persist_card_game_result(record: CardGameRoundRecord, result: dict, is_retry: bool) -> None:
    key = student_key(record.get("student_id"))
    wrong_ids = [item["card_id"] for item in result["items"] if not item["is_correct"]]
    if wrong_ids:
        existing = get_wrong_records(key)
        save_wrong_records(key, [*wrong_ids, *[c for c in existing if c not in wrong_ids]][:30])

    append_card_game_report(key, {
        "round_id": record["round_id"],
        "title": record["title"],
        "topic": record["topic"],
        "difficulty": record["difficulty"],
        "score": result["score"],
        "total": result["total"],
        "wrong_card_ids": wrong_ids,
        "is_retry": is_retry,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


def get_card_game_report(student_id: str) -> dict:
    key = student_key(student_id)
    reports = get_card_game_reports(key)
    wrong_card_ids = get_wrong_records(key)
    total_rounds = len(reports)
    total_cards = sum(r["total"] for r in reports)
    total_score = sum(r["score"] for r in reports)
    recent_reports = reports[-8:]
    return {
        "student_id": student_id,
        "rounds_played": total_rounds,
        "total_score": total_score,
        "total_cards": total_cards,
        "accuracy": round(total_score / total_cards, 2) if total_cards else 0,
        "wrong_card_ids": wrong_card_ids,
        "recent_rounds": recent_reports,
        "review_tip": build_card_game_report_tip(total_score, total_cards, wrong_card_ids),
        "next_recommendation": "下一局会优先复现最近错过的事件卡。" if wrong_card_ids else "可以尝试更高难度或切换专题，扩大时间线覆盖面。",
    }


def public_event(event: TimelineEventInternal) -> dict:
    return {
        "id": event["id"],
        "title": event["title"],
        "period": event["period"],
        "summary": event["summary"],
        "topic": event["topic"],
    }


def public_card(card: TimelineEventInternal) -> dict:
    return {
        "id": card["id"],
        "card_type": "event",
        "title": card["title"],
        "period": card["period"],
        "clue": card["summary"],
        "topic": card["topic"],
    }


def normalize_difficulty(difficulty: str) -> TimelineDifficulty:
    aliases = {"standard": "normal", "challenge": "hard"}
    normalized = aliases.get((difficulty or "easy").strip().lower(), (difficulty or "easy").strip().lower())
    if normalized in {"easy", "normal", "hard"}:
        return normalized  # type: ignore[return-value]
    raise ValueError("不支持的时间线难度，请选择 easy、normal、hard、standard 或 challenge。")


def choose_level(
    grade: str | None,
    difficulty: TimelineDifficulty,
    topic: str | None,
) -> TimelineLevel:
    candidates = TIMELINE_LEVELS
    if topic:
        topic_matches = [level for level in candidates if topic in level["topic"] or level["topic"] in topic]
        if topic_matches:
            candidates = topic_matches
    if grade:
        grade_matches = [level for level in candidates if grade in level["grade"]]
        if grade_matches:
            candidates = grade_matches
    difficulty_matches = [level for level in candidates if level["difficulty"] == difficulty]
    if difficulty_matches:
        candidates = difficulty_matches
    return choice(candidates)


def validate_submission(correct_order: list[str], ordered_event_ids: list[str]) -> None:
    if len(ordered_event_ids) != len(correct_order):
        raise ValueError("提交的事件数量不完整，请确认所有事件都已排序。")
    if len(set(ordered_event_ids)) != len(ordered_event_ids):
        raise ValueError("提交中存在重复事件，请重新调整顺序。")
    if set(ordered_event_ids) != set(correct_order):
        raise ValueError("提交中包含不属于本局的事件，请重新开始一局。")


def build_learning_tip(score: int, total: int, record: TimelineRoundRecord) -> str:
    if score == total:
        return f"你已经掌握了《{record['title']}》的先后顺序，可以继续思考这些事件之间的因果联系。"
    if score >= total * 0.6:
        return "大部分顺序已经接近正确，建议重点复盘标红事件所处的朝代、时期和前后背景。"
    return "建议先抓住朝代或时期的大框架，再比较具体事件的先后；先判断属于古代、近代还是世界近代史，再细排事件。"


def build_card_game_learning_tip(score: int, total: int, record: CardGameRoundRecord) -> str:
    if score == total:
        return f"时间巨轮已经完全校准。你可以继续追问《{record['title']}》中这些事件之间的因果联系。"
    if score >= total * 0.6:
        return "大部分卡牌已经接近正确，修正时优先比较标红卡牌与相邻事件的时期和背景。"
    return "建议先把卡牌分成古代、近代或世界史的大框架，再用人物、制度变化和事件影响判断先后。"


def build_card_game_report_tip(total_score: int, total_cards: int, wrong_card_ids: list[str]) -> str:
    if total_cards == 0:
        return "还没有完成过时间巨轮挑战，先开始一局建立个人复盘记录。"
    if total_score == total_cards:
        return "最近的卡牌排序全部正确，可以切换专题或挑战更高难度。"
    if wrong_card_ids:
        return "复盘时重点关注错题卡所处的大时期，再比较它和相邻事件的因果关系。"
    return "继续保持，把每局讲解中的关键词整理成自己的时间轴。"


def student_key(student_id: str | None) -> str:
    return (student_id or "anonymous").strip() or "anonymous"



