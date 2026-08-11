"""Build the 18-ad SG creative batch — 6 CBO campaigns, RM60/day each, all PAUSED.

Operator-approved 2026-08-11 after a full creative-collection pass (18 items, 16 distinct
angles). Every asset ships from the repo (assets/sg_batch/**) rather than Drive, so the build
needs no Drive sharing and is fully reproducible on the runner.

Grouping is by ANGLE FAMILY, and it is not cosmetic — several creatives reuse the SAME parent
testimonial screenshots, so putting them in one ad set would make them bid against each other
with duplicate proof. The mutual-exclusion pairs (verified while cataloguing) are:
    #4 ↔ #13   10岁女/12岁女 WhatsApp 数据      #9  ↔ #14  Rina 群聊三段
    #10 ↔ #14  Aug24→Mar25 庆祝贴              #10 ↔ #12  March 8 推荐贴
    #3  ↔ #10  同族（饮食禁忌 / 反补品）        #6  ↔ #18  同族（性早熟 / 青春期）
The groups below are arranged so no pair lands in the same ad set.

  A 知识科普  sleep · growing-pain · WHO chart (+A03 video)  ← widest audience, also reaches
                                                               parents who care about focus/grades
  B 迷思打破  diet taboo · exercise myth · puberty countdown
  C 见证证明  best-of reviews · results montage · review collage
  D 焦虑情感  height stopped · 3hr webinar/性早熟 · beat genetics
  E 低期待值  stalled restart · "didn't believe" · 2cm witness      (anti-hype, small wins)
  F 备用      doctor-said-no · no-supplements   ← evidence is recycled inside C's best-of deck,
                                                  so keep this one PAUSED until C has data

Targeting is CLONED LIVE from the named SG ad sets (operator chose "沿用已验证兴趣"), same
mechanism as build_1_1_5_winners.py. Only 4 verified audiences exist for 6 campaigns, so two
are reused — noted per group and logged at run time.

Copy rules applied to every ad (locked with the operator during collection):
  · Simplified Chinese · 马丁医师 · NO url in the body (the landing page lives on the CTA button)
  · credentials use the official landing-page wording (诊所和社区药局执业超过10年 / 中医跟学超过10年)
  · no hashtags · no engagement bait ("记得保存分享" removed) · 6–8cm everywhere
Split-banner carousels (cards 1+2 are two halves of one wide image) have their order LOCKED by
the card_NN filenames — do not re-sort. Affected: diet_taboo, review_best_of, stalled_restart,
sleep_gh, growing_pain.

Idempotent: media uploads are cached in state/media_cache.json by the synthetic file_id below,
and each group's campaign/adset/ad ids live in its own state file, so a re-dispatch is a no-op.
"""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from adbot import media
from adbot.build_1_1_10 import build
from adbot.clients.graph import GraphError
from adbot.commands import graph_client
from adbot.creative_groups import CAROUSEL, SINGLE_IMAGE, VIDEO, Asset, Unit
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets" / "sg_batch"
PREFIX = "[SG] 儿童长高方程式"
DAILY_MYR = 60

SG_GEO = {"countries": ["SG"]}
SG_EXCL = [{"id": "120226672882380093"},          # 15 days complete registration (已注册)
           {"id": "120246547080720093"}]          # 马丁 1997 Paid Student (已购买)
DETAIL_KEYS = ["interests", "behaviors", "life_events", "family_statuses", "industries",
               "income", "education_statuses", "work_positions", "work_employers",
               "relationship_statuses", "user_adclusters", "moms"]

# ── shared copy blocks ───────────────────────────────────────────────────────────
BIO = ("你好，我是马丁医师，来自台湾的专业儿童长高专家，\n"
       "诊所和社区药局执业超过 10 年、中医跟学超过 10 年，\n"
       "已帮助超过 6000 位家长解决孩子长不高的烦恼。")
CURRICULUM = ("✅ 中西医都没说清楚的长高关键\n"
              "✅ 长不高的四大体质偏差\n"
              "✅ 长高关键营养素的正确摄取\n"
              "✅ 打开肠胃黄金吸收力\n"
              "✅ 比跳绳更有效的科学增高运动\n"
              "✅ 成长金三角：把身高、注意力、睡眠一起管好\n"
              "✅ 儿童长高推拿手法")
NEGATIVES = ("❌ 不逼孩子吃又黑又难吃的食物\n"
             "❌ 不用把牛奶当水灌\n"
             "❌ 不用每天疯狂跳绳")
CTA_LINE = "点下方按钮，马上免费报名《儿童长高方程式》👇"


def tail(intro: str, curriculum: str = CURRICULUM, closing: str = "") -> str:
    parts = [intro.rstrip(), "", BIO, "",
             "在这堂免费线上课里，你会学到：", curriculum, "",
             "而且这些方法：", NEGATIVES, ""]
    if closing:
        parts += [closing.rstrip(), ""]
    parts.append(CTA_LINE)
    return "\n".join(parts)


# ── the 18 ads ───────────────────────────────────────────────────────────────────
# dir      : folder under assets/sg_batch/<group>/ ; card order = sorted filenames
# kind     : CAROUSEL | SINGLE_IMAGE | VIDEO
# cards    : per-card {name, description} for carousels (index-aligned; [] = inherit headline)
ADS: List[Dict[str, Any]] = [
    # ══ A · 知识科普组 ════════════════════════════════════════════════════════════
    {
        "group": "a_knowledge", "dir": "sleep_gh", "kind": CAROUSEL,
        "content_id": "sg-睡眠-生长激素黄金时段",
        "headline": "晚上 9 点到凌晨 3 点，才是长高黄金时段",
        "description": "免费线上课 · 睡眠、饮食、体质，一次讲清楚",
        "cards": [{}, {},
                  {"name": "生长激素黄金时段", "description": "晚上 9 点到凌晨 3 点"},
                  {"name": "各年龄段该睡多久", "description": "5–12 岁 9–11 小时"},
                  {"name": "睡不好的三个后果", "description": "身高 · 精神 · 课业"}],
        "caption": tail(
            "不是让孩子睡得多，就长得快 😴\n\n"
            "真正的关键，是他有没有睡在生长激素分泌的黄金时段。\n\n"
            "生长激素主要在孩子睡眠时分泌，\n"
            "尤其是晚上 9 点到凌晨 3 点这段时间。\n"
            "如果错过了这个时段，即使睡得再多，\n"
            "也达不到最佳的生长效果。\n\n"
            "也就是说 —— 11 点才上床的孩子，\n"
            "就算睡满 9 小时，也已经错过了大半个高峰期。\n\n"
            "顺便对照一下，你家孩子睡够了吗？\n"
            "· 1–3 岁：11–14 小时\n"
            "· 3–5 岁：10–13 小时\n"
            "· 5–12 岁：9–11 小时\n"
            "· 12–18 岁：8–10 小时\n\n"
            "而睡不够、睡太晚，影响的不只是身高：\n"
            "📉 身高 —— 错过生长激素高峰，身高增长受影响\n"
            "😵 精神 —— 白天精神不振，影响学习和日常活动\n"
            "📚 课业 —— 上课容易分心、打瞌睡，学习效果大打折扣\n\n"
            "很多家长以为孩子长不高是「吃得不够」，\n"
            "其实问题常常出在「睡得太晚」。",
            closing="孩子的长高黄金期一生只有一次，错过就补不回来。"),
    },
    {
        "group": "a_knowledge", "dir": "growing_pain", "kind": CAROUSEL,
        "content_id": "sg-生长痛-晚上喊脚痛",
        "headline": "孩子晚上喊脚痛？可能是生长痛",
        "description": "免费线上课 · 教你判断、缓解，还有长高推拿手法",
        "cards": [{}, {},
                  {"name": "什么是生长痛", "description": "3–12 岁，25%–40% 都经历过"},
                  {"name": "为什么会痛", "description": "骨骼快，肌腱肌肉跟不上"},
                  {"name": "怎么判断", "description": "早上不痛 · 一小时内缓解"}],
        "caption": tail(
            "孩子一到晚上就喊脚痛，半夜还会痛醒，\n"
            "问他哪里痛，他又说不清楚 ——\n"
            "那很可能是「生长痛」。\n\n"
            "3～12 岁的孩子里，约有 25%～40% 都经历过。\n\n"
            "为什么会痛？\n"
            "因为发育不平衡：\n"
            "骨骼长得快，但四肢的神经、肌腱、肌肉跟不上，\n"
            "腿部肌肉被拉紧，就产生了酸痛。\n\n"
            "换句话说 —— 会痛，往往代表他正在长。\n\n"
            "怎么判断是不是生长痛？\n"
            "✅ 早上起床时没感觉，傍晚或睡眠途中才痛\n"
            "✅ 多发生在小腿、膝盖、大腿、脚踝\n"
            "✅ 通常一小时内就缓解\n"
            "✅ 第二天睡醒完全没影响\n\n"
            "⚠️ 但如果孩子的痛不符合这几点 ——\n"
            "白天也痛、每次都痛在同一个固定位置、\n"
            "有红肿发热、走路一跛一跛，或者连续好几天不退，\n"
            "就不要当成生长痛处理，请尽快带他看医生。\n\n"
            "如果确认是生长痛，真正要做的不是止痛，\n"
            "而是帮孩子把跟不上的肌肉和筋膜松开，\n"
            "再把营养和睡眠补上，让骨骼和软组织同步成长。",
            curriculum=("✅ 儿童长高推拿手法 —— 正好用来放松紧绷的腿部肌肉\n"
                        "✅ 长不高的四大体质偏差\n"
                        "✅ 长高关键营养素的正确摄取\n"
                        "✅ 打开肠胃黄金吸收力\n"
                        "✅ 比跳绳更有效的科学增高运动\n"
                        "✅ 成长金三角：把身高、注意力、睡眠一起管好"),
            closing="孩子会痛，是身体在长的信号。\n别只是让他忍过去 —— 顺势把该补的补上。"),
    },
    {
        "group": "a_knowledge", "dir": "who_chart", "kind": SINGLE_IMAGE,
        "content_id": "sg-WHO对照表-达标吗-静态图",
        "headline": "你的孩子身高，达标了吗？",
        "description": "对照 WHO 标准 · 一堂免费线上课，揭秘一年增高 6cm",
        "caption": tail(
            "妈妈请注意 ⚠️ 你的孩子身高，达标了吗？\n\n"
            "这是世界卫生组织（WHO）5–15 岁的平均身高对照表：\n\n"
            "👦 男孩：5岁 110.3 · 7岁 122.0 · 9岁 133.5 · 11岁 144.5 · 13岁 156.2 · 15岁 165.7cm\n"
            "👧 女孩：5岁 109.6 · 7岁 120.8 · 9岁 132.4 · 11岁 144.2 · 13岁 153.6 · 15岁 157.5cm\n\n"
            "现在就去量一量你的孩子，对照看看差了多少。\n\n"
            "如果他明显低于同龄标准，或者你还发现：\n"
            "· 明显比同班同学矮一颗头\n"
            "· 保健品吃了一堆，牛奶天天当水喝\n"
            "· 每天跳绳 500 下，最后还是没长高 😱\n\n"
            "先别急 —— 只要孩子还不到 15 岁，他就还有机会长高。\n"
            "不是孩子长不高，是方法用错了。\n\n"
            "而且我要提醒你：刚好「贴着平均线」也不代表安全。\n"
            "真正要看的是他每年长多少，以及成长空间还剩多少。",
            closing="长高不能等。3–15 岁的黄金期一生只有一次，错过就补不回来。"),
    },
    {
        "group": "a_knowledge", "dir": "who_video", "kind": VIDEO,
        "content_id": "sg-WHO对照表-达标吗-视频A03",
        "headline": "你的孩子身高，达标了吗？",
        "description": "对照 WHO 标准 · 免费线上课",
        # deliberately the SAME angle as who_chart → same ad set = clean video-vs-image format test
        "caption": tail(
            "妈妈请注意 ⚠️ 你的孩子身高，达标了吗？\n\n"
            "对照世界卫生组织（WHO）5–15 岁的平均身高，\n"
            "很多妈妈量完都吓一跳。\n\n"
            "如果孩子明显低于同龄标准，或者你还发现：\n"
            "· 明显比同班同学矮一颗头\n"
            "· 保健品吃了一堆，牛奶天天当水喝\n"
            "· 每天跳绳 500 下，最后还是没长高 😱\n\n"
            "先别急 —— 只要孩子还不到 15 岁，他就还有机会长高。\n"
            "不是孩子长不高，是方法用错了。\n\n"
            "而且刚好「贴着平均线」也不代表安全。\n"
            "真正要看的是他每年长多少，以及成长空间还剩多少。",
            closing="长高不能等。3–15 岁的黄金期一生只有一次，错过就补不回来。"),
    },

    # ══ B · 迷思打破组 ════════════════════════════════════════════════════════════
    {
        "group": "b_myths", "dir": "diet_taboo", "kind": CAROUSEL,
        "content_id": "sg-饮食禁忌-别再逼孩子喝牛奶",
        "headline": "别再逼孩子喝牛奶了",
        "description": "5 种害孩子长不高的食物，一堂免费课讲清楚",
        "cards": [{}, {},
                  {"name": "小麦 & 奶制品", "description": "容易造成体内湿气堆积"},
                  {"name": "高糖甜食", "description": "干扰内分泌，打乱生长激素"},
                  {"name": "油炸食品", "description": "反式脂肪妨碍营养吸收"},
                  {"name": "高盐饮食", "description": "加速钙质流失"},
                  {"name": "碳酸饮料", "description": "磷酸降低骨骼密度"},
                  {"name": "这堂课你会学到", "description": "中西医结合的长高关键"},
                  {"name": "你也放心", "description": "不逼吃 · 不灌奶 · 不狂跳绳"},
                  {"name": "免费报名分享会", "description": "已帮助 6000+ 位家长"}],
        "caption": tail(
            "别再逼孩子喝牛奶了 🥛\n"
            "这 5 种食物，才是害孩子长不高的元凶：\n\n"
            "❌ 小麦制品 & 奶制品 —— 容易造成体内湿气堆积\n"
            "❌ 高糖甜食 —— 干扰内分泌，打乱生长激素分泌\n"
            "❌ 油炸食品 —— 反式脂肪妨碍营养吸收\n"
            "❌ 高盐饮食 —— 加速钙质流失\n"
            "❌ 碳酸饮料 —— 磷酸降低骨骼密度\n\n"
            "很多家长天天让孩子喝牛奶、补钙，\n"
            "却没发现真正挡住孩子长高的，\n"
            "是餐桌上这几样「看起来很正常」的食物。",
            closing="免费名额有限，孩子的长高黄金期只有一次，错过就补不回来。"),
    },
    {
        "group": "b_myths", "dir": "exercise_myth", "kind": SINGLE_IMAGE,
        "content_id": "sg-运动迷思-这5种运动越做越矮",
        "headline": "这 5 种运动，越做越矮",
        "description": "一堂免费线上课，教你比跳绳更有效的增高运动",
        "caption": tail(
            "孩子每天跳绳 500 下，可能越跳越矮 😫\n\n"
            "想长高，不一定要靠这 5 种运动 ——\n"
            "有些运动做过头，只会让孩子越做越矮：\n\n"
            "❌ 每天跳绳 500 下\n"
            "❌ 天天打篮球\n"
            "❌ 大量力量训练\n"
            "❌ 长时间跑步锻炼\n"
            "❌ 高强度体操练习\n\n"
            "为什么？\n"
            "因为过度运动会让孩子筋膜紧绷、骨头之间打不开，\n"
            "反而挡住了长高的空间。\n\n"
            "合理的运动确实有助于长高，\n"
            "但「练得越多 = 长得越高」这个观念，是错的。",
            closing="免费名额有限，孩子的黄金成长期一生只有一次。"),
    },
    {
        "group": "b_myths", "dir": "puberty_countdown", "kind": SINGLE_IMAGE,
        "content_id": "sg-青春期倒计时-初经变声不是开始",
        "headline": "初经、变声，不是青春期的开始",
        "description": "免费线上课 · 看到这些信号，代表倒计时已经开始",
        "caption": tail(
            "女儿来了初经、儿子开始变声长喉结 ——\n"
            "很多家长以为：孩子终于进入青春期了。\n\n"
            "错。\n\n"
            "那不是青春期的开始，那是青春期的中后期。\n"
            "意思是：孩子的成长倒计时，已经开始了。\n\n"
            "真正的青春期启动，比这些看得见的信号早得多。\n"
            "等你看到初经、看到喉结，\n"
            "能长的空间，其实已经不多了。\n\n"
            "所以预防性早熟，要比你想的更早开始：\n"
            "1️⃣ 少吃鸡皮和动物内脏\n"
            "2️⃣ 少吃速食和油炸食品\n"
            "3️⃣ 只吃当季水果\n"
            "4️⃣ 避免太早给孩子进补\n\n"
            "「那我的孩子已经进入青春期了，还有救吗？」\n\n"
            "好消息是：只要孩子还在 3～15 岁之间，就还有机会再长高。\n"
            "只是到了这个阶段，方法必须更准 —— 不能再一样一样乱试。",
            closing="倒计时已经开始了，但还没结束。"),
    },

    # ══ C · 见证证明组 ════════════════════════════════════════════════════════════
    {
        "group": "c_proof", "dir": "review_best_of", "kind": CAROUSEL,
        "content_id": "sg-好评合集-7个月12cm",
        "headline": "7 个月，哥哥长了 12cm",
        "description": "6000+ 家长的共同见证 · 免费线上课",
        # card_04 (Rina 群聊) ships REDACTED: the chat header leaked a parent's phone number, so
        # that strip is painted out with the bubble's own background. See docs note in the F entry.
        "cards": [{}, {},
                  {"name": "平均一个月长 1cm", "description": "两个孩子，半年多的记录"},
                  {"name": "医生说不会再长，结果逆转", "description": "18 岁大女儿长了 3cm"},
                  {"name": "7 个月 12cm", "description": "「我发梦都不敢想」"}],
        "caption": tail(
            "「从 11 月上课到现在，哥哥总共长了 12cm。\n"
            "我发梦都不敢想。」\n\n"
            "这是一位妈妈 6 月在群里发的分享：\n"
            "👦 儿子 14 岁（还没过生日）—— 157cm\n"
            "👧 女儿 11 岁（刚过生日）—— 152.7cm\n\n"
            "对比三月份，哥哥长了 5cm、妹妹长了 4.7cm；\n"
            "从去年 11 月上课算起，哥哥一共长了 12cm、妹妹长了 8.7cm。\n\n"
            "她还补了一句，看得我很有感触：\n"
            "「哥哥从小都是班里矮小的，一年级到五年级排队都排前三 ——\n"
            "如果那是考试排名就好咯。」\n\n"
            "这样的分享，我每个月都会收到很多。\n\n"
            "有妈妈说：「裤子越来越短，我才发现她真的长高了。」\n"
            "她家两个孩子，从去年 8 月到今年 3 月，平均一个月长 1cm。\n\n"
            "也有妈妈说：「医生说不会再长了。」\n"
            "结果 18 岁的大女儿长了 3cm，现在比 151cm 的妈妈还高；\n"
            "4 岁的弟弟戒掉麦类奶制品后，几个月内长了 5cm。\n\n"
            "他们的孩子体质不同、年龄不同、起点也不同。\n"
            "但方向是同一个：先把体质调对，成长自然会跟上。",
            closing="孩子的成长期一生只有一次，错过就补不回来。"),
    },
    {
        "group": "c_proof", "dir": "results_montage", "kind": CAROUSEL,
        "content_id": "sg-成果见证-14张复量记录",
        "headline": "免费线上分享会 · 儿童长高方程式",
        "description": "一年健康长高 6～8cm 的方法，名额有限",
        "cards": [{"name": "1 年 长高 8cm"}, {"name": "1 年 1 个月 长高 6.5cm"},
                  {"name": "11 个月 长高 5.7cm"}, {"name": "10 个月 长高 5.1cm"},
                  {"name": "5 个月 长高 5cm"}, {"name": "10 个月 长高 4.5cm"},
                  {"name": "5 个月 长高 4.2cm", "description": "蛋奶素的孩子也可以"},
                  {"name": "4 个月 长高 4.1cm"}, {"name": "1 年 2 个月 长高 4cm"},
                  {"name": "3 个月 长高 2.7cm", "description": "12 岁男生 · 過動症"}],
        "caption": tail(
            "【这些孩子，都在马丁医师的方法下长高了 📈】\n"
            "2 个月长高 1.2cm、5 个月长高 4.2cm、一年长高 8cm……\n"
            "👆 这些不是广告数字，是一位位真实家长传来的复量记录。\n\n"
            "他们的孩子年龄不同、体质不同、起点也不同 ——\n"
            "有蛋奶素的孩子，有已经来初经的女生，\n"
            "也有被认为「已经长不高」的大孩子。\n\n"
            "但方向是同一个：先把体质调对，成长自然会跟上。",
            closing="孩子的长高黄金期只有一次，错过就补不回来。\n别让孩子因为身高而自卑 🌱"),
    },
    {
        "group": "c_proof", "dir": "review_collage", "kind": SINGLE_IMAGE,
        "content_id": "sg-好评集锦-看过专科西医和营养师",
        "headline": "看过专科西医和营养师，她还是改了做法",
        "description": "免费线上课 · 别人有效的方法，未必适合你孩子的体质",
        "caption": tail(
            "「我看过儿童长高专科的西医，也见过营养师。\n"
            "听完马丁老师的解说，才有恍然大悟的感觉。」\n\n"
            "这是一位妈妈自己写下的话。\n"
            "她不是没做过功课 —— 她是做得比大多数家长都多的那种。\n\n"
            "让她转念的是这一点：\n"
            "「西医的方法，是把同样的模式和食谱用在几乎每一个孩子身上，\n"
            "没有把体质纳入考量。」\n\n"
            "这也是我一直想告诉家长的事：\n"
            "孩子长不高，往往不是因为你做得不够，\n"
            "而是因为别人家有效的方法，未必适合你家孩子的体质。\n\n"
            "另一位妈妈的记录更实在：\n"
            "她的女儿卡了 4 个月没长高，\n"
            "调整之后 7 个星期，终于长了 1cm。\n"
            "她做的是：忌麦奶、煲药膳、偶尔做筋膜运动、\n"
            "睡前听音乐，再帮孩子做手部推拿。\n\n"
            "不是什么惊天动地的大改造，只是把方向换对了。",
            closing="别让身高成为孩子一辈子的遗憾。"),
    },

    # ══ D · 焦虑情感组 ════════════════════════════════════════════════════════════
    {
        "group": "d_emotion", "dir": "height_stopped", "kind": SINGLE_IMAGE,
        "content_id": "sg-生长缓慢-孩子身高停止不长了",
        "headline": "孩子身高停止不长了？",
        "description": "一年长不到 6cm？免费线上课教你怎么救",
        "caption": tail(
            "你的孩子每年只长 1–2cm？\n"
            "明明已经很努力了，为什么还是比同龄人矮一截？\n\n"
            "其实，孩子长得慢的根本原因，\n"
            "往往是体质和营养吸收出了问题 ——\n"
            "不是多喝牛奶、多跳绳就能解决的。\n\n"
            "尤其如果你是这几种家长，请一定看下去：\n"
            "📌 孩子一年长不到 6cm\n"
            "📌 骨龄超前 / 落后\n"
            "📌 有性早熟迹象\n"
            "📌 注意力不集中\n"
            "📌 有睡眠障碍\n"
            "📌 课业压力大、长不高\n\n"
            "我已经帮助来自台湾、马来西亚、曼谷、澳洲、加拿大和美国的\n"
            "6000+ 名孩子，每年实现健康增高 6–8cm。\n"
            "这些孩子当中，有很多曾被认为「已经长不高了」，\n"
            "但在调整之后，他们依然长回来了。\n\n"
            "如果你也遇过这些情况：\n"
            "· 担心孩子遗传到父母的身高，再也长不高\n"
            "· 网上的偏方、保健品、运动都试过了，孩子还是没长\n"
            "· 看过中医也看过西医，调理了很久却不见效\n\n"
            "放心。作为一位父亲，我很清楚家长的心情。\n"
            "❌ 我不会使用药物或任何不自然的方法\n"
            "❌ 不会逼孩子吃难以下咽的食物\n"
            "❌ 更不会要求孩子拼命运动",
            closing="孩子的黄金成长期，一生只有一次，错过就补不回来。"),
    },
    {
        "group": "d_emotion", "dir": "puberty_3hr", "kind": SINGLE_IMAGE,
        "content_id": "sg-黄金期-3小时分享会-性早熟",
        "headline": "3～15 岁，孩子一生只有一次的长高黄金期",
        "description": "3 小时免费线上分享会 · 科学长高 + 预防性早熟",
        "caption": tail(
            "爸爸妈妈，别让孩子因为身高矮小而终身自卑 😭\n\n"
            "3～15 岁，是孩子一生只有一次的黄金长高期。\n"
            "把握住了，他这辈子会比同龄人高出一截。\n\n"
            "如果你家孩子有这些情况，请一定看下去：\n"
            "· 明显比同班同学矮一颗头\n"
            "· 保健品吃了一堆，牛奶天天当水喝\n"
            "· 每天跳绳 500 下，最后还是没长高 😱\n"
            "· 总是睡不好，注意力越来越差\n"
            "· 已经出现性早熟迹象（长胡须／胸部发育／来月经）\n\n"
            "别担心 —— 只要孩子还不到 15 岁，他就还有机会长高。\n"
            "不是他长不高，是现在用的方法不对。\n\n"
            "在免费的 3 小时线上分享会里，\n"
            "我会分享一套科学的长高方式，\n"
            "结合「中医看体质、西医看营养」，透过全方位营养调理，\n"
            "让孩子每年健康长高 6–8cm，同时预防性早熟 ✨",
            closing="免费名额有限，孩子的黄金成长期一生只有一次，错过就补不回来。"),
    },
    {
        "group": "d_emotion", "dir": "beat_genetics", "kind": SINGLE_IMAGE,
        "content_id": "sg-突破基因-爸妈不高孩子还有机会吗",
        "headline": "就算爸妈都不高，孩子一样能长高",
        "description": "免费线上分享会 · 突破基因，每年健康增高 6–8cm",
        "caption": tail(
            "爸爸妈妈都不高，孩子还有机会长高吗？😰\n\n"
            "这大概是最多家长私下问我的问题。\n"
            "尤其东南亚的华人家庭，平均身高本来就不高。\n\n"
            "为了让孩子长高，很多父母什么都试过：\n"
            "❓ 每天一杯牛奶补钙\n"
            "❓ 煲花生根给孩子喝\n"
            "❓ 买了一堆保健品\n"
            "❓ 逼孩子跳绳、打篮球、拼命运动\n\n"
            "但是 ——\n"
            "🔺 你确定孩子的体质，真的适合这些方法吗？\n"
            "🔺 你确定吃某一种产品或食物，就一定能长高吗？\n"
            "🔺 如果这些方法都没效，你就要放弃孩子的身高了吗？\n\n"
            "我想告诉你的是：基因决定的是范围，不是结果。\n"
            "就算家族基因身高不高，孩子一样可以每年健康增高 6–8cm。",
            closing="成长只有一次，别错过 3–15 岁的黄金增高期。"),
    },

    # ══ E · 低期待值组（反夸张） ═══════════════════════════════════════════════════
    {
        "group": "e_lowkey", "dir": "stalled_restart", "kind": CAROUSEL,
        "content_id": "sg-停滞重启-停了两年又开始长",
        "headline": "停了两年，两个月又开始长了",
        "description": "免费线上课 · 孩子长不高，可能只是体质卡住了",
        "cards": [{}, {},
                  {"name": "停长 2 年 → 2 个月见效", "description": "拍舌头看体质"},
                  {"name": "停滞半年 → 再破 2cm", "description": "先修肠胃，再进补"},
                  {"name": "15 岁 4 个月长 2cm", "description": "气色也变好了"}],
        "caption": tail(
            "「之前两年，孩子好像停止长高了。\n"
            "我以为她来了 mc，就不会再长了。」\n\n"
            "结果两个月，就长高了 1cm 多。\n\n"
            "这位妈妈做的第一件事，只是拍了女儿的舌头让我看体质。\n\n"
            "很多家长以为「停了就是停了」。\n"
            "但停滞的原因，往往不是孩子长高的能力没了，\n"
            "而是体质卡住了 —— 而体质，是可以调的。\n\n"
            "另一位妈妈的儿子 15 岁。\n"
            "13、14 岁时一年还能长 7cm，\n"
            "到了 15 岁，从八月尾量是 170，就一直停在 170。\n"
            "看了舌头才知道，他属于 2、3、4 型混合体质，\n"
            "我请她先把第 2 型的肠胃修复好，再谈进补。\n\n"
            "年底再量：172cm。\n"
            "一个月长 2cm，打破了他自己以往的记录。\n\n"
            "还有一位妈妈说：\n"
            "「参加了 3 天课程，学会了解孩子的体质，慢慢改变他的饮食习惯。\n"
            "接近 15 岁的儿子，4 个月里长高了 2cm。\n"
            "更重要的是他的气色变好了 —— 以前脸色暗黄，现在又白又亮。」\n\n"
            "如果你的孩子还不到 15 岁，他就还在长高黄金期。\n"
            "就算已经停了一阵子，也不代表结束了。",
            curriculum=("✅ 中西医结合的全面长高方案\n"
                        "✅ 长不高的四大体质偏差\n"
                        "✅ 让孩子重新长起来的关键顺序（为什么要先修肠胃、再进补）\n"
                        "✅ 如何用饮食、运动和简单推拿帮助孩子长高\n"
                        "✅ 打破传统的长高误区，找到真正有效的方法"),
            closing="孩子的黄金成长期一生只有一次。"),
    },
    {
        "group": "e_lowkey", "dir": "didnt_believe", "kind": SINGLE_IMAGE,
        "content_id": "sg-怀疑者-一开始我也不信",
        "headline": "一开始我也不信，结果两个月长了 3–4cm",
        "description": "免费线上课 · 几个小改变，让孩子的成长线重新启动",
        "caption": tail(
            "「一开始我也不信。」\n\n"
            "她女儿 4 岁，将近一年没长高，身高一直卡在 97–98cm。\n"
            "两个月后她随手量了一下 ——\n"
            "101cm。终于突破 100 了 🎉\n\n"
            "但最打动我的，是她接下来那句：\n"
            "「虽然还是班上最矮小的，可是有进步就有动力。」\n\n"
            "而她做的事，其实小得让人意外：\n"
            "· 羊奶粉换成豆奶粉（还好孩子接受得到）\n"
            "· 开始做筋膜初级运动\n"
            "· 每晚听音乐 —— 她自己说，这是最简单最容易做到的\n"
            "· 儿子的早餐换成破壁机粮食\n\n"
            "连 Milo 都没戒掉。\n"
            "孩子实在很难戒，那就先不戒。\n\n"
            "你看，帮孩子长高不是要你把整个生活翻掉，\n"
            "而是先把几个方向换对。\n\n"
            "很多爸妈的烦恼都一样 👇\n"
            "🔸 明明每天喝奶，孩子就是不长高\n"
            "🔸 担心孩子一直偏矮，越来越没自信\n"
            "🔸 市面上一堆增高补品，怕踩雷又烧钱",
            closing="别让身高成为孩子一辈子的遗憾。"),
    },
    {
        "group": "e_lowkey", "dir": "witness_2cm", "kind": SINGLE_IMAGE,
        "content_id": "sg-小胜利-也许只是2cm但是希望的开始",
        "headline": "「也许只是 2cm，但对我们来说是希望的开始」",
        "description": "免费线上课 · 不靠保健品，从体质根本帮孩子长高",
        "caption": tail(
            "「对别人来说，也许只是 2cm。\n"
            "但对我们来说，是希望的开始。」\n\n"
            "这位妈妈今年 5 月才上课。\n"
            "过去几年，孩子一年才长 2–3cm。\n"
            "她心里焦虑，却一直告诉自己：每个孩子都有自己的成长节奏。\n\n"
            "两个月前，她抱着「试试看」的心态报了线上课。\n\n"
            "📏 2025 / 5 / 8 — 124.5cm\n"
            "📏 2025 / 7 / 20 — 126.5cm\n"
            "两个月，长了 2cm。\n\n"
            "她自己是这样写的：\n"
            "「原来用对方法、搭配好生活节奏，\n"
            "真的能让孩子的成长打开一个新方向。\n"
            "当然，鼻子敏感的问题还没完全改善，我们还要继续努力调理体质。\n"
            "但今天，想先庆祝这一点点小小的成长喜悦。」\n\n"
            "我特别喜欢这一则分享。\n"
            "因为它没有奇迹，也没有夸张 ——\n"
            "只是一个原本一年长 2–3cm 的孩子，\n"
            "用两个月，走完了过去要花大半年甚至一整年才走完的路。\n\n"
            "看着孩子一年才长 2cm，怎么可能不急？\n"
            "明明饮食均衡、作息正常，身高却原地踏步；\n"
            "牛奶、补品、钙片都试过了，钱花了，孩子还是没起色。\n\n"
            "问题往往不在「吃什么」，而在体质。",
            closing="别让身高成为孩子一辈子的遗憾。"),
    },

    # ══ F · 备用组（证据与 C 组重叠，先建后放） ═══════════════════════════════════
    # REDACTION NOTE (2026-08-11): the Rina group-chat screenshots used by this ad and by C's
    # best-of card 4 leaked a parent's mobile number in the truncated chat header — dim grey, easy
    # to miss, but a real person's number. Both images now ship with that strip painted out using
    # the bubble's own background tone (see scripts/redact_phone_numbers.py). Nothing was ever
    # delivered with the number on it: the ads were PAUSED from creation.
    {
        "group": "f_backup", "dir": "doctor_said_no", "kind": SINGLE_IMAGE,
        "content_id": "sg-权威反转-医生说他不会再长了",
        "headline": "医生说他不会再长了，结果呢？",
        "description": "免费线上课 · 被判「长不高」的孩子，后来长回来了",
        "caption": tail(
            "「医生说她骨龄快封闭了，最多就 149cm。」\n\n"
            "几个月后，这位妈妈自己在群里发了消息：\n"
            "女儿长了 3cm，现在比 151cm 的妈妈还要高 🎉\n\n"
            "这不是我写的文案，是家长亲自截图分享的。\n\n"
            "同一位妈妈的 4 岁儿子，以前每个月都感冒发烧、挑食，\n"
            "身高体重都不及同龄孩子；\n"
            "戒掉麦类和奶制品、调整体质之后，\n"
            "不但不用每个月跑医院，几个月内还长高了 5cm。\n\n"
            "你是不是也听过类似的话？\n"
            "🔸 医生说骨龄快封闭了，孩子大概就这样了\n"
            "🔸 每年长不到 2cm，中医西医都看过，就是没起色\n"
            "🔸 全家为孩子的身高操碎心，却不知道还能做什么\n\n"
            "我想告诉你的是：被判「不会再长」的孩子，我看过太多后来长回来了。",
            closing="别让身高成为孩子一辈子的遗憾。"),
    },
    {
        "group": "f_backup", "dir": "no_supplements", "kind": SINGLE_IMAGE,
        "content_id": "sg-反补品-不吃保健品孩子反而长高了",
        "headline": "不吃保健品，孩子反而长高了",
        "description": "免费线上课 · 不推产品，教你把孩子的体质调对",
        "caption": tail(
            "不喝牛奶、不吃保健品，孩子反而长高了 😲\n\n"
            "这位妈妈一开始也不信。\n"
            "直到第 3 个月，她发现女儿的裙子突然变短了。\n\n"
            "这是家长自己记的成长台账：\n"
            "📅 2024 年 8 月：六岁女儿 106cm、四岁儿子 98cm\n"
            "📅 2025 年 3 月：七岁女儿 112cm、五岁儿子 105cm\n"
            "→ 半年多，女儿长了 6cm、儿子长了 7cm，平均一个月约 1cm\n\n"
            "她后来在推荐里写：\n"
            "「上课之前，孩子一直都是全班最矮，身型小一岁，\n"
            "试过长高汤但没看到显著的果效。\n"
            "上完三天的课，老师不推产品，甚至说不用买 supplement 给孩子，\n"
            "主打了解孩子体质、调理好他们的身体，\n"
            "自然就可以透过日常饮食、生活习惯让他们长高。」\n\n"
            "你是不是也试过：\n"
            "❌ 牛奶喝了好几年，身高没什么动静\n"
            "❌ 保健品买了一堆，效果像买个心安\n"
            "❌ 每年体检看到成长曲线就皱眉\n\n"
            "问题往往不是「补得不够」，而是方向错了。\n"
            "不是补钙补钙再补钙，孩子就会长高。",
            closing="别让身高成为孩子一辈子的遗憾。"),
    },
]

# group → (ad-set name / clone source, state key, campaign label)
# NOTE: only 4 verified SG audiences exist for 6 campaigns, so two are reused (A/E on Parents,
# C/F on Health & Wellness). F is the designated backup and should stay PAUSED until C has data,
# which keeps the real overlap down to A↔E.
GROUPS: List[Dict[str, str]] = [
    {"key": "a_knowledge", "clone": "Parents",                  "adset_name": "Parents 3-17 | 知识科普",
     "state_key": "entities_sgbatch_a_knowledge", "label": "知识科普 | A"},
    {"key": "b_myths",     "clone": "Milk & Bread",             "adset_name": "Milk & Bread | 迷思打破",
     "state_key": "entities_sgbatch_b_myths",     "label": "迷思打破 | B"},
    {"key": "c_proof",     "clone": "Health & Wellness",        "adset_name": "Health & Wellness | 见证证明",
     "state_key": "entities_sgbatch_c_proof",     "label": "见证证明 | C"},
    {"key": "d_emotion",   "clone": "Family and Relationships", "adset_name": "Family and Relationships | 焦虑情感",
     "state_key": "entities_sgbatch_d_emotion",   "label": "焦虑情感 | D"},
    {"key": "e_lowkey",    "clone": "Parents",                  "adset_name": "Parents 3-17 | 低期待值",
     "state_key": "entities_sgbatch_e_lowkey",    "label": "低期待值 | E"},
    {"key": "f_backup",    "clone": "Health & Wellness",        "adset_name": "Health & Wellness | 备用",
     "state_key": "entities_sgbatch_f_backup",    "label": "备用 | F"},
]


def _richness(t: dict) -> int:
    if not isinstance(t, dict):
        return 0
    cnt = lambda spec: sum(len(spec.get(k) or []) for k in DETAIL_KEYS)
    return cnt(t) + sum(cnt(grp) for grp in (t.get("flexible_spec") or []))


def clone_targeting(adsets: List[dict], name: str) -> Tuple[Optional[dict], Optional[str]]:
    """Clone interest/behavior targeting from the richest SG ad set matching `name` → SG spec."""
    key = name.strip().lower()
    matches = [a for a in adsets if (a.get("name") or "").strip().lower() == key] \
        or [a for a in adsets if key in (a.get("name") or "").strip().lower()]
    if not matches:
        return None, None
    best = max(matches, key=lambda a: _richness(a.get("targeting") or {}))
    t = best.get("targeting") or {}
    adv_raw = (t.get("targeting_automation") or {}).get("advantage_audience")
    adv = 1 if adv_raw is None else int(adv_raw)
    age_min, age_max = int(t.get("age_min") or 25), int(t.get("age_max") or 65)
    if adv == 1 and age_min > 25:
        age_min = 25
    spec: Dict[str, Any] = {
        "geo_locations": SG_GEO, "age_min": age_min, "age_max": age_max,
        "targeting_automation": {"advantage_audience": adv},
        "excluded_custom_audiences": SG_EXCL, "locales": [1004],
    }
    if t.get("genders"):
        spec["genders"] = t["genders"]
    fs = t.get("flexible_spec")
    if fs:
        spec["flexible_spec"] = fs
    else:
        legacy = {k: t[k] for k in DETAIL_KEYS if t.get(k)}
        if legacy:
            spec["flexible_spec"] = [legacy]
    return spec, best.get("name")


def make_unit(ad: Dict[str, Any]) -> Unit:
    """Build a Unit from the repo assets. Card order = sorted filenames (card_01, card_02, …),
    which is what locks the split-banner halves (cards 1+2 of several decks are two halves of
    one wide image and MUST stay adjacent and in order)."""
    folder = ASSET_ROOT / ad["group"] / ad["dir"]
    files = sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))
    if not files:
        raise SystemExit(f"no assets in {folder}")
    if ad["kind"] != CAROUSEL and len(files) != 1:
        raise SystemExit(f"{ad['kind']} expects exactly 1 file, found {len(files)} in {folder}")
    if ad["kind"] == CAROUSEL and not (2 <= len(files) <= 10):
        raise SystemExit(f"carousel needs 2–10 cards, found {len(files)} in {folder}")

    assets = []
    for p in files:
        mime = mimetypes.guess_type(p.name)[0] or "image/jpeg"
        assets.append(Asset(
            file_id=f"sgbatch/{ad['group']}/{ad['dir']}/{p.name}",   # stable key for media_cache
            name=f"{ad['dir']}/{p.name}", mime=mime, local_path=str(p)))
    return Unit(content_id=ad["content_id"], kind=ad["kind"], assets=assets)


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path

    s.naming.prefix = PREFIX
    s.meta.budget.level = "CAMPAIGN"                 # CBO
    s.meta.budget.daily_amount_myr = DAILY_MYR

    # Meta rate-limits this account (code 17) when a run uploads a lot of media at once. Everything
    # is resumable (media_cache + per-group state), so a partial run just needs a re-dispatch —
    # set ADBOT_BATCH_GROUPS to a comma-separated list of group keys to redo only what failed.
    only = {x.strip() for x in (os.environ.get("ADBOT_BATCH_GROUPS") or "").split(",") if x.strip()}
    if only:
        unknown = only - {g_["key"] for g_ in GROUPS}
        if unknown:
            raise SystemExit(f"unknown group key(s) in ADBOT_BATCH_GROUPS: {sorted(unknown)}")
        log.info("group filter active → %s", sorted(only))

    sg_adsets = g._get_all(f"{acct}/adsets", {"fields": "name,effective_status,targeting", "limit": 500})
    log.info("pulled %d SG ad sets for cloning", len(sg_adsets))

    summary: List[str] = []
    total_ads = 0
    for grp in GROUPS:
        if only and grp["key"] not in only:
            continue
        ads = [a for a in ADS if a["group"] == grp["key"]]
        if not ads:
            continue
        log.info("═" * 88)
        log.info("── %s  (%d ads)", grp["label"], len(ads))

        spec, src = clone_targeting(sg_adsets, grp["clone"])
        if spec is None:
            log.error("!! no SG ad set like %r to clone — SKIPPING %s", grp["clone"], grp["label"])
            summary.append(f"  ⏭ SKIP {grp['label']} (no clone source {grp['clone']!r})")
            continue
        log.info("   targeting ← %r (age %s-%s · adv=%s · %d detail entries)", src,
                 spec["age_min"], spec["age_max"],
                 (spec.get("targeting_automation") or {}).get("advantage_audience"),
                 _richness({"flexible_spec": spec.get("flexible_spec", [])}))

        units, captions = [], {}
        for ad in ads:
            unit = make_unit(ad)
            units.append(unit)
            captions[ad["content_id"]] = {
                "caption": ad["caption"], "headline": ad["headline"],
                "description": ad.get("description", ""),
                "carousel_card_texts": ad.get("cards") or [],
            }
            log.info("   · %-11s %-2d asset(s)  %s", ad["kind"], len(unit.assets), ad["content_id"])

        media.sync_media(g, s, units, dry_run=False)

        try:
            ent = build(g, s, units=units, captions=captions, dry_run=False,
                        label=grp["label"], state_key=grp["state_key"],
                        adset_name=grp["adset_name"], targeting_override=spec)
        except GraphError as exc:
            log.error("!! build failed for %s: %s", grp["label"], exc)
            summary.append(f"  ✗ FAIL {grp['label']}: {exc}")
            continue

        n = len(ent.get("ad_ids") or [])
        total_ads += n
        summary.append(f"  {grp['label']:16} campaign={ent['campaign_id']} adset={ent['adset_id']} ads={n}")
        log.info("   ✓ campaign %s · adset %s · %d ad(s)", ent["campaign_id"], ent["adset_id"], n)

    log.info("═" * 88)
    for line in summary:
        log.info(line)
    live_groups = len([x for x in summary if x.strip().startswith(("知", "迷", "见", "焦", "低", "备"))])
    final_summary(
        log,
        f"SG creative batch built PAUSED: {total_ads} ads across {live_groups} CBO campaigns "
        f"(RM{DAILY_MYR}/day each). Review in Ads Manager, then activate. Suggested first wave: "
        f"A 知识科普 + B 迷思打破 + C 见证证明 (RM180/day). Keep F 备用 paused until C has data — "
        f"its testimonials are already inside C's best-of carousel.")


if __name__ == "__main__":
    main()
