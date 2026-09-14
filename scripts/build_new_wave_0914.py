"""New Wave 0914: 3 proven-targeting campaigns × 15 single-ad ad sets, ALL PAUSED.

Operator's spec (14 Sep, restated line by line, answered "45，paused"):
    · THREE new ABO campaigns, one per Paid-Student-List top-converting ad set:
        Food & Drink + Milk        ← clone adset 120250912724510093 (26 sales, most ever)
        Family & Relationships     ← clone adset 120257269400410093 (16 sales, hottest 60d;
                                     Adv+ OFF and 18-65 copied verbatim and re-verified)
        Health & Wellness          ← clone adset 120256984987300093 (16 sales, cheapest CPA)
    · Each campaign: 15 ad sets (same cloned targeting, named exactly like the source ad
      set so sheet attribution keeps folding by name), RM30/day ABO each, ONE ad per set.
    · The 15 ads = 13 new videos (新马 V1-V4 + H3/H4/H6/H7/H8, 北美 H3/H4/H5/H6) with the
      operator-approved block-layout copies, + Hook 1 今晚回家 & Hook 2 旧鞋当尺 reusing the
      corrected 10,000-version creatives (ad names keep the exact historical strings).
    · 45 chains × RM30 = RM1,350/day ONCE ACTIVATED — but everything is built with the
      CAMPAIGNS PAUSED (ad sets and ads created ACTIVE underneath), so nothing delivers
      until the operator flips the three campaigns on. One creative per video, shared by
      its three campaign copies (social proof pools).

Idempotent via state/entities_new_wave_0914.json — uploads and entities are cached and a
re-dispatch resumes where it stopped (Meta account throttles are expected on a build this
size: the run exits with a clear RATE-LIMITED message and code 75; dispatch again ~30 min
later and it continues).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from adbot.clients.drive import DriveClient
from adbot.clients.graph import GraphError, TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_PATH = Path("state") / "entities_new_wave_0914.json"
PREFIX = "[SG] 儿童长高方程式"
DAILY_MINOR = 3000                      # RM30/day per ad set, operator-fixed
PACE_SECONDS = 1.0                      # gentle pacing between entity creations

CAMPAIGNS: List[Dict[str, str]] = [
    {"key": "food", "label": "Food & Drink + Milk | New Wave 0914 | 1-15-15",
     "clone": "120250912724510093"},
    {"key": "fr", "label": "Family & Relationships | New Wave 0914 | 1-15-15",
     "clone": "120257269400410093"},
    {"key": "hw", "label": "Health & Wellness | New Wave 0914 | 1-15-15",
     "clone": "120256984987300093"},
]

# The two rebuilt 0907 creatives with the corrected 10,000+ proof line ("新的，10000 的").
# Ad names MUST stay the exact historical strings so sheet attribution folds correctly.
FIXED_ADS: List[Dict[str, str]] = [
    {"key": "hook1", "ad_name": "Hook 1：今晚回家检查三件事", "creative_id": "2605128693280832"},
    {"key": "hook2", "ad_name": "Hook 2：旧鞋当尺", "creative_id": "1648374606961366"},
]

# 13 new videos: Drive file ids verified against the operator's shared files
# (Martin July 新馬 V1-V4 / 新馬 H3 H4 H6 H7 H8 / 北美 H3 H4 H5 H6).
VIDEOS: List[Dict[str, str]] = [
    {"key": "v1", "drive": "1BZUVP0xwLFDSMBzKANVn9j9l6VuFKCde",
     "ad_name": "Video 1：去年半个头，今年一粒头", "title": "🔴 去年矮半个头，今年矮一个头"},
    {"key": "v2", "drive": "1ewvREiDHVY7bgjtKytBN8HQgu6c6juSq",
     "ad_name": "Video 2：新马家长最怕这个东西！", "title": "🔴 方法试了十种，孩子长了几公分？"},
    {"key": "v3", "drive": "1ewEdAXZIKMyIExl4YQX8G2Ug20eMKdGF",
     "ad_name": "Video 3：基因不是保证书", "title": "🔴 爸妈都高，孩子反而长输了？"},
    {"key": "v4", "drive": "10RtRCKkt4hYEtrvmiUQmY7NGS3oFwQV5",
     "ad_name": "Video 4：每天记录身高，却看不懂成长信号", "title": "🔴 每天量身高，却看不懂成长信号"},
    {"key": "xh3", "drive": "15l55Ts4anwW-n3Wyh4tenCWMcz3lDbVb",
     "ad_name": "Hook 3：倒掉牛奶", "title": "🔴 这杯牛奶，我劝你倒掉"},
    {"key": "xh4", "drive": "1dCK9KyWImQX6pwEznNBllGMgNs5V6Scd",
     "ad_name": "Hook 4：门框上的线", "title": "🔴 门框上那条线，多久没画新的了？"},
    {"key": "xh6", "drive": "11MiKuLQO6XiXOk2PAjWQueUhjHicE-Hu",
     "ad_name": "Hook 6：没有人会告诉你", "title": "🔴 这件事，没有人会主动告诉你"},
    {"key": "xh7", "drive": "1xtFaAhBFf6JTEHd4PCEi3TROppCE7HQo",
     "ad_name": "Hook 7：算给你看", "title": "🔴 三年花掉的钱 vs 长高的公分数"},
    {"key": "xh8", "drive": "1iUV7fpAmAj1Kb9TCM5ZjJMXoH1iPPY0Y",
     "ad_name": "Hook 8：我劝你，先别买", "title": "🔴 医师劝你：先别买任何长高产品"},
    {"key": "nh3", "drive": "1-3zQy23RkXvqbaw7aKQC35GhQWFu1p9b",
     "ad_name": "Hook 3：卷尺越量越焦虑", "title": "🔴 越量越焦虑的那把卷尺"},
    {"key": "nh4", "drive": "1Gyz5CyouzH5IMgDfld5p_XZ_N8fF25iV",
     "ad_name": "Hook 4：保健品叫你丢掉", "title": "🔴 这些保健品，我常叫家长直接丢掉"},
    {"key": "nh5", "drive": "1cCW8PpfP2mQ2tKQkEnP8TOeEfgYvgsUi",
     "ad_name": "Hook 5：基因打脸", "title": "🔴 爸妈不高，孩子就矮定了？错。"},
    {"key": "nh6", "drive": "1MwyKx7cIzeRssWMWZxjCsTwTntr_JzwC",
     "ad_name": "Hook 6：最矮的那一个", "title": "🔴 合照最前排、最矮的那一个"},
]

# Operator-approved bodies (14 Sep "上"), block layout per their reference: sentences
# stacked, blank line only between sections. Verbatim — do not edit.
BODIES: Dict[str, str] = {
    "v1": """📏 去年站在同学旁边，只矮半个头。
今年再站在一起，差距已经变成一整个头。
不是你的孩子变矮了，
是别的孩子一直在长，他的成长速度没有跟上。

很多家长只盯着孩子"现在几公分"，
👉 却没算过：过去半年，他到底长了几公分？
这个数字，才是真相。

孩子的成长阶段不会无限延长，继续等，不会自动解决这些问题：
😴 晚睡
🥣 偏食
🌿 消化状态不好
🏃 运动方式错了
这些每天都在无形中拖慢孩子的身高。

大家好，我是马丁医师 🧑🏻‍⚕️🇹🇼
来自台湾的儿童长高专家，拥有超过 10 年中西医整合经验，
已帮助 10,000+ 位孩子健康长高！

💡 在我的免费线上课程中，你将学习：
✅ 怎么记录孩子自己的成长速度，而不是拿他跟别人比
✅ 睡眠、饮食、运动，先调哪一个才有效
✅ 怎么抓住成长关键期，帮孩子健康长高

⚠️ 名额有限，坐满即止！
点击以下 Button 立即免费报名，
别等差距变成两个头，才开始找答案！我们课程见！👋""",
    "v2": """🗣️「要长高就喝牛奶、跳绳啦。」
🗣️「再试试钙片、蛋白粉、成长奶粉……」
新马的家长最怕的，其实是这个——
📉 方法一个换一个，却从来没有记录和判断：
孩子有没有长？哪个习惯改了有差别？哪个问题该先处理？
统统不知道。

我不会叫你再买多一样补品，
我反而会先问你四个问题：
📏 过去半年，孩子长了多少？
🥣 吃进去的东西，身体吸收得好不好？
🏃 现在的运动，适合他当下的状态吗？
😴 每天几点睡？

其实想让孩子每年健康长高 6-8cm 并不难，
👉 但第一步，是先看懂他的体质类型！

大家好，我是马丁医师 🧑🏻‍⚕️🇹🇼
来自台湾的儿童长高专家，拥有超过 10 年中西医整合经验，
已帮助 10,000+ 位孩子健康长高！

💡 如果你的孩子今年 5-15 岁、方法试了很多身高却没变化，来我的免费线上分享会：
✅ 保健品商不想让你知道的长高真相
✅ 怎么用天然的方式帮孩子调体质、长身高
✅ 让孩子不再动不动就生病、过敏

⚠️ 名额有限，坐满即止！
点击以下 Button 立即免费报名，
先看懂孩子卡在哪里，才知道下一步做什么！我们课程见！👋""",
    "v3": """🧬 个子高的爸爸妈妈，反而最容易耽误孩子的身高。
🗣️「我们两个都不矮，孩子迟早会长，不用急。」
就是这句话，可能正在偷走孩子最后的长高空间。

👉 基因，只决定身高的范围，
能不能长到范围的最高点，靠的是后天。
父母高，是拿到一副好牌，
但好牌不会打，一样输。

更何况在新马这种又湿又热的气候：
🥛 每天逼他喝牛奶、吃面包、塞长高保健品，
在湿热体质里反而让脾胃更重、吸收更差，
营养全卡在半路，进不了骨头。

这些年我见过太多：
矮个子父母的孩子，长到全班前几高；
高个子父母的孩子，一路被同学追过，连遗传身高都没达到。
真正拉开差距的从来不是基因，
是父母有没有在黄金成长期，做对每一步。

大家好，我是马丁医师 🧑🏻‍⚕️🇹🇼
来自台湾的儿童长高专家，拥有超过 10 年中西医整合经验，
已帮助 10,000+ 位孩子健康长高！

💡 在我的免费线上课程中，你将学习：
✅ 一步步检视孩子的饮食、睡眠、运动和身体状态
✅ 从孩子的舌头，看懂他的体质
✅ 找到真正适合他的调理方式，把这副好牌打出去

⚠️ 名额有限，坐满即止！
点击以下 Button 立即免费报名，
别让一句「我们基因好」，赌掉孩子的身高！我们课程见！👋""",
    "v4": """📏 你是不是也一样？
每天帮孩子量身高，
却不知道他现在还剩多少成长空间。
👉 尺只告诉你"现在几公分"，不会告诉你是什么在拖慢他。

其实很多日常习惯，都在影响孩子的成长：
😴 晚睡
🥣 偏食
🌿 消化状态不好
🏃 运动方式不合适
看起来是小事，其实每天都在无形中影响身高。

我看一个孩子的成长状况，从来不是先看尺，
是先看他的生活习惯。
很多时候不是孩子不能长，
而是家长不知道：哪一个地方需要先调整。

大家好，我是马丁医师 🧑🏻‍⚕️🇹🇼
来自台湾的儿童长高专家，拥有超过 10 年中西医整合经验，
已帮助 10,000+ 位孩子健康长高！

💡 在我的免费线上分享会，我会讲三件事：
✅ 孩子成长过程中的重要信号
✅ 家长每天可以观察哪些地方
✅ 发现问题后，下一步应该怎么调整

⚠️ 如果你的孩子现在 10-16 岁，不要再只是盲目量身高！
点击以下 Button 立即免费报名，
别等孩子长大后，才后悔没早点看懂信号！我们课程见！👋""",
    "xh3": """🥛 我把整杯牛奶，倒进了水槽。
不是牛奶不好——
👉 是你孩子现在的身体，用不了它。
倒了，比喝了强。

我知道你已经很努力了：
每天盯着他喝牛奶、买最贵的保健品、逼他跳绳跳到膝盖痛。
📉 结果他吃得比谁都多，身高就是不动。
营养要变成身高，得先过肠胃这一关，
肠胃卡住了，补再多也是白补。

今晚回家，检查三件事，一分钟就够：
🛑 过去一年，是不是只长了一两公分？
🛑 吃很多，但不长肉、也不长高？
🛑 经常鼻子敏感、皮肤痒、便秘，晚上睡不安稳？
⚠️ 三个全中——这是他的吸收系统，在跟你求救。

大家好，我是马丁医师 🧑🏻‍⚕️🇹🇼
来自台湾的儿童长高专家，拥有超过 10 年中西医整合经验，
已帮助 10,000+ 位孩子健康长高！
我的做法只有一句话：先健康，后长高，不打针、不塞补品。

💡 在我的免费线上课程中，你将学习：
✅ 孩子长不高的底层原因到底是什么
✅ 过敏、肠胃、睡眠，先后顺序怎么排
✅ 生长板闭合之前，你还可以为他做什么

⚠️ 名额有限，坐满即止！
点击以下 Button 立即免费报名，
别让孩子错过长高黄金期！我们课程见！👋""",
    "xh4": """📏 门框上的身高线，
你多久，没有画新的一条了？
我知道你不敢量，
👉 因为量了，就要面对。

但不面对，不代表没发生：
📉 过去这一年，他可能只长了一两公分。
🗣️「男生晚长啦。」「再等一两年看看。」
等，等不来身高，
真正该做的，是搞清楚他卡在哪。

今晚回家，检查三件事：
🛑 一年是不是只长了一两公分？
🛑 吃很多却不长肉、不长高？
🛑 鼻子敏感、皮肤痒、便秘、睡不安稳？
⚠️ 三个全中，不是"发育慢"，是吸收系统在求救。

大家好，我是马丁医师 🧑🏻‍⚕️🇹🇼
来自台湾的儿童长高专家，拥有超过 10 年中西医整合经验，
已帮助 10,000+ 位孩子健康长高！

💡 在我的免费线上课程中，你将学习：
✅ 从三个信号找出孩子长不高的原因
✅ 肠胃、睡眠、过敏的调整顺序
✅ 生长板闭合前，家长还能做什么

⚠️ 名额有限，坐满即止！
点击以下 Button 立即免费报名，
别让门框上的线，永远停在去年！我们课程见！👋""",
    "xh6": """🤫 有件事，没有人会主动告诉你。
不是医生，不是老师，
更不是卖保健品给你的那个人。
👉 因为讲了，对他们没有好处。

但你必须知道：
孩子长不高，多数不是"缺了什么"，
是身体根本吸收不进去。
📉 所以你补得越多，失望越多。

自己验证，今晚就检查三件事：
🛑 一年是不是只长了一两公分？
🛑 吃很多却不长肉、不长高？
🛑 鼻子敏感、皮肤痒、便秘、睡不安稳？
⚠️ 三个全中——吸收系统在求救。

大家好，我是马丁医师 🧑🏻‍⚕️🇹🇼
来自台湾的儿童长高专家，拥有超过 10 年中西医整合经验，
已帮助 10,000+ 位孩子健康长高！
不打针、不塞补品，先健康，后长高。

💡 在我的免费线上课程中，我会公开：
✅ 保健品商不想让你知道的长高真相
✅ 为什么补了没效，吸收才是关键
✅ 生长板闭合前的正确调整顺序

⚠️ 名额有限，坐满即止！
点击以下 Button 立即免费报名，
知道的人，永远先一步！我们课程见！👋""",
    "xh7": """🧮 我们来算一笔账。
保健品，一个月多少钱？
牛奶、补品、运动班、看医生……
三年下来，你一共花了多少？
👉 再问一句：他长高了几公分？

如果这笔账让你心里一沉——
问题从来不是你花得不够，
是钱没有花对地方。
营养进不了身体，买再贵都是白补。

先检查孩子的吸收系统有没有卡住：
🛑 一年是不是只长了一两公分？
🛑 吃很多却不长肉、不长高？
🛑 鼻子敏感、皮肤痒、便秘、睡不安稳？
⚠️ 三个全中，钱再砸下去也一样。

大家好，我是马丁医师 🧑🏻‍⚕️🇹🇼
来自台湾的儿童长高专家，拥有超过 10 年中西医整合经验，
已帮助 10,000+ 位孩子健康长高！

💡 在我的免费线上课程中，你将学习：
✅ 为什么补了没效，吸收才是关键
✅ 哪些钱不用再花、哪些事必须先做
✅ 生长板闭合前的优先顺序

⚠️ 名额有限，坐满即止！
点击以下 Button 立即免费报名，
这堂课免费，比你已经花掉的都便宜！我们课程见！👋""",
    "xh8": """✋ 我是执照中医师，
我劝你——先别买任何长高产品。
一个都别买。
👉 至少，在你搞清楚这件事之前：
你孩子的身体，到底吸不吸收得进去？

吸收不了，买得越贵，越是帮倒忙。
我知道你已经很努力了，
但营养要变成身高，得先过肠胃这一关。

今晚回家，检查三件事：
🛑 一年是不是只长了一两公分？
🛑 吃很多却不长肉、不长高？
🛑 鼻子敏感、皮肤痒、便秘、睡不安稳？
⚠️ 三个全中——先别补，先调。

大家好，我是马丁医师 🧑🏻‍⚕️🇹🇼
来自台湾的儿童长高专家，拥有超过 10 年中西医整合经验，
已帮助 10,000+ 位孩子健康长高！
先健康，后长高：不打针、不塞补品。

💡 在我的免费线上课程中，你将学习：
✅ 花钱之前，必须先懂的三件事
✅ 怎么判断孩子的吸收系统卡在哪
✅ 生长板闭合前的正确顺序

⚠️ 名额有限，坐满即止！
点击以下 Button 立即免费报名，
先搞清楚，再花钱！我们课程见！👋""",
    "nh3": """📏 很多爸妈，一年帮孩子量一次身高。
越量越焦虑——
因为那个数字，几乎没动。
👉 但真正的问题不在这把尺上，在他身体里面。

你已经很努力了：
牛奶、保健品、运动班……
📉 他吃得比谁都多，身高就是不动。
不是孩子天生矮，
是营养卡在肠胃，进不了骨头。

今晚回家，检查三件事：
🛑 一年是不是只长了一两公分？
🛑 吃很多却不长肉、不长高？
🛑 鼻子敏感、皮肤痒、便秘、睡不安稳？
⚠️ 三个全中——吸收系统在求救。

大家好，我是马丁医师 🧑🏻‍⚕️🇹🇼
来自台湾的儿童长高专家，拥有超过 10 年中西医整合经验，
已帮助 10,000+ 位孩子健康长高！

💡 在我的免费线上课程中，你将学习：
✅ 三个信号背后的底层原因
✅ 先调什么、再补什么的顺序
✅ 生长板闭合前，怎么抓回每一公分

⚠️ 名额有限，坐满即止！
点击以下 Button 立即免费报名，
下次拉开卷尺之前，先把里面的问题搞定！我们课程见！👋""",
    "nh4": """🗑️ 桌上那一排瓶瓶罐罐，
我常常叫家长——直接丢掉。
不是它没用，
👉 是你孩子的身体，现在根本吸收不了。
买得越贵，可能只是越帮倒忙。

营养要变成身高，得先过肠胃这一关，
肠胃卡住了，补再多也是白补。

你孩子有没有这个问题？检查三件事：
🛑 一年是不是只长了一两公分？
🛑 吃很多却不长肉、不长高？
🛑 鼻子敏感、皮肤痒、便秘、睡不安稳？
⚠️ 三个全中——先停手，先调理。

大家好，我是马丁医师 🧑🏻‍⚕️🇹🇼
来自台湾的儿童长高专家，拥有超过 10 年中西医整合经验，
已帮助 10,000+ 位孩子健康长高！
先健康，后长高：不打针、不塞补品。

💡 在我的免费线上课程中，你将学习：
✅ 补之前必须先做对的那一步
✅ 怎么把孩子的吸收系统调回来
✅ 生长板闭合前的行动清单

⚠️ 名额有限，坐满即止！
点击以下 Button 立即免费报名，
先修好吸收，再谈进补！我们课程见！👋""",
    "nh5": """🧬 你跟另一半都不高，
就认定孩子这辈子矮定了？
👉 错。基因只决定范围，
决定不了他最后长到哪。

这十年我见过太多：
矮个子父母的孩子，长到全班前几高。
差别不在基因，
在关键那几年，有没有把身体调对。

孩子长不高，多数是营养吸收不进去，检查三件事：
🛑 一年是不是只长了一两公分？
🛑 吃很多却不长肉、不长高？
🛑 鼻子敏感、皮肤痒、便秘、睡不安稳？
⚠️ 三个全中——卡住他的是这个，不是基因。

大家好，我是马丁医师 🧑🏻‍⚕️🇹🇼
来自台湾的儿童长高专家，拥有超过 10 年中西医整合经验，
已帮助 10,000+ 位孩子健康长高！

💡 在我的免费线上课程中，你将学习：
✅ 基因之外，真正决定身高的三件事
✅ 怎么帮孩子把潜力发挥到范围的最高点
✅ 生长板闭合前的黄金调整期

⚠️ 名额有限，坐满即止！
点击以下 Button 立即免费报名，
范围是天生的，结果是养出来的！我们课程见！👋""",
    "nh6": """📷 班级大合照，你一眼就找到你的孩子——
因为他总是站在最前排、最矮的那一个。
🗣️ 你嘴上说「顺其自然」，
心里其实很急。
👉 我懂。而且我要告诉你：这件事，真的还有得救。

孩子长不高，多数不是天生，
是身体吸收不了，营养进不了骨头。

今晚回家，检查三件事：
🛑 一年是不是只长了一两公分？
🛑 吃很多却不长肉、不长高？
🛑 鼻子敏感、皮肤痒、便秘、睡不安稳？
⚠️ 三个全中——吸收系统在求救。
💔 别让身高，变成孩子心里的疙瘩。

大家好，我是马丁医师 🧑🏻‍⚕️🇹🇼
来自台湾的儿童长高专家，拥有超过 10 年中西医整合经验，
已帮助 10,000+ 位孩子健康长高！

💡 在我的免费线上课程中，你将学习：
✅ 从三个信号看懂孩子卡在哪
✅ 先健康后长高的调整顺序
✅ 生长板闭合前，家长能做的事

⚠️ 名额有限，坐满即止！
点击以下 Button 立即免费报名，
下一张合照，让他站后面一点！我们课程见！👋""",
}

DETAIL_KEYS = ["interests", "behaviors", "life_events", "family_statuses", "industries",
               "income", "education_statuses", "work_positions", "work_employers",
               "relationship_statuses", "user_adclusters", "moms"]


def clone_targeting(g, adset_id: str, s) -> Dict[str, Any]:
    t = g._request("GET", adset_id, params={"fields": "targeting"}).get("targeting") or {}
    adv_raw = (t.get("targeting_automation") or {}).get("advantage_audience")
    adv = 1 if adv_raw is None else int(adv_raw)
    age_min, age_max = int(t.get("age_min") or 25), int(t.get("age_max") or 65)
    if adv == 1 and age_min > 25:
        age_min = 25
    spec: Dict[str, Any] = {
        "geo_locations": {"countries": s.meta.targeting.countries or ["SG"]},
        "age_min": age_min, "age_max": age_max,
        "targeting_automation": {"advantage_audience": adv},
        "excluded_custom_audiences": [{"id": i} for i in
                                      (s.meta.targeting.excluded_custom_audiences or [])],
        "locales": s.meta.targeting.locales or [1004],
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
    return spec


def verify_expansion(g, adset_id: str, spec: Dict[str, Any], intended: int, log) -> None:
    if intended != 0:
        return
    t = g._request("GET", adset_id, params={"fields": "targeting"}).get("targeting") or {}
    adv = int((t.get("targeting_automation") or {}).get("advantage_audience") or 0)
    if adv == 0:
        return
    fix = dict(spec)
    fix["targeting_automation"] = {"advantage_audience": 0}
    g._request("POST", adset_id, data={"targeting": json.dumps(fix)})
    t2 = g._request("GET", adset_id, params={"fields": "targeting"}).get("targeting") or {}
    adv2 = int((t2.get("targeting_automation") or {}).get("advantage_audience") or 0)
    log.info("   expansion drifted (adv=%s) → rewrote → adv=%s%s", adv, adv2,
             "" if adv2 == 0 else " — STILL ON, fix by hand")


def build() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    m = s.meta
    conv = m.conversion_domain_bare or None

    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}

    def persist() -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    # ── 0) the two fixed creatives must still exist ─────────────────────────────
    for f in FIXED_ADS:
        try:
            g.get_object(f["creative_id"], "id,name")
        except GraphError as exc:
            log.error("Fixed creative %s (%s) unreadable: %s — cannot build its 3 ads; "
                      "STOPPING before anything is created. Tell the operator.",
                      f["creative_id"], f["ad_name"], exc)
            raise
    log.info("Fixed 10,000-version creatives verified: hook1 %s · hook2 %s",
             FIXED_ADS[0]["creative_id"], FIXED_ADS[1]["creative_id"])

    # ── 1) 13 videos → 13 shared creatives (cached) ─────────────────────────────
    creatives: Dict[str, Any] = st.setdefault("creatives", {})
    drive = None
    for v in VIDEOS:
        rec: Dict[str, Any] = creatives.get(v["key"]) or {}
        if rec.get("creative_id"):
            log.info("── %s: reuse creative %s", v["key"], rec["creative_id"])
            creatives[v["key"]] = rec
            continue
        video_id = rec.get("video_id")
        if video_id:
            thumb = rec.get("thumb") or g.get_video_thumbnail(video_id)
        else:
            if drive is None:
                drive = DriveClient(s.secrets.google_sa_json)
            path = Path(f"/tmp/{v['key']}.mp4")
            drive.download_file(v["drive"], path)
            log.info("── %s: downloaded %.1f MB → uploading…", v["key"],
                     path.stat().st_size / 1_048_576)
            video_id = g.upload_video(acct, str(path), name=v["ad_name"])
            thumb = g.get_video_thumbnail(video_id)
            path.unlink(missing_ok=True)
            rec.update({"video_id": video_id, "thumb": thumb})
            creatives[v["key"]] = rec
            persist()
        cta = {"type": m.call_to_action, "value": {"link": m.lead_destination.link_url}}
        vdata: Dict[str, Any] = {"video_id": video_id, "title": v["title"],
                                 "message": BODIES[v["key"]], "call_to_action": cta}
        if thumb:
            vdata["image_url"] = thumb
        story: Dict[str, Any] = {"page_id": m.page_id, "video_data": vdata}
        if m.instagram_user_id:
            story["instagram_user_id"] = m.instagram_user_id
        fields: Dict[str, Any] = {"name": v["ad_name"], "object_story_spec": story}
        if m.url_tags:
            fields["url_tags"] = m.url_tags
        rec["creative_id"] = g.create_adcreative(acct, **fields)["id"]
        creatives[v["key"]] = rec
        persist()
        log.info("── %s: + creative %s (video %s)", v["key"], rec["creative_id"], video_id)
        time.sleep(PACE_SECONDS)

    ads_plan: List[Dict[str, str]] = (
        [{"key": v["key"], "ad_name": v["ad_name"]} for v in VIDEOS]
        + [{"key": f["key"], "ad_name": f["ad_name"]} for f in FIXED_ADS])
    creative_of = {v["key"]: creatives[v["key"]]["creative_id"] for v in VIDEOS}
    creative_of.update({f["key"]: f["creative_id"] for f in FIXED_ADS})

    # ── 2) three PAUSED campaigns × 15 (ad set + ad) ────────────────────────────
    camps: Dict[str, Any] = st.setdefault("campaigns", {})
    built_rows: List[str] = []
    for c in CAMPAIGNS:
        log.info("═" * 88)
        cst: Dict[str, Any] = camps.setdefault(c["key"], {})

        src = g.get_object(c["clone"], "id,name")
        adset_name = src.get("name") or c["label"]
        spec = clone_targeting(g, c["clone"], s)
        adv = int((spec.get("targeting_automation") or {}).get("advantage_audience") or 1)
        cst["source_adset"] = {"id": c["clone"], "name": adset_name, "adv": adv}
        log.info("── targeting source %s %r (Adv+ %s · %s-%s)", c["clone"], adset_name,
                 "ON" if adv else "OFF", spec.get("age_min"), spec.get("age_max"))

        if cst.get("campaign_id"):        # staleness check: operator may have deleted it
            try:
                eff = g.get_object(cst["campaign_id"], "effective_status").get("effective_status")
            except GraphError:
                eff = "DELETED"
            if eff in ("DELETED", "ARCHIVED"):
                log.info("── stored campaign %s is %s → rebuilding fresh", cst["campaign_id"], eff)
                cst.pop("campaign_id", None)
                cst.pop("units", None)
        if cst.get("campaign_id"):
            log.info("── reuse campaign %s", cst["campaign_id"])
        else:
            fields = {"name": f"{PREFIX} | {c['label']}", "objective": m.objective,
                      "buying_type": "AUCTION", "status": "PAUSED",
                      "special_ad_categories": m.special_ad_categories,
                      "is_adset_budget_sharing_enabled": False}
            if m.regional_regulated_categories:
                fields["regional_regulated_categories"] = m.regional_regulated_categories
            cst["campaign_id"] = g.create_campaign(acct, **fields)["id"]
            persist()
            log.info("── + campaign %s %r (PAUSED)", cst["campaign_id"], fields["name"])
            time.sleep(PACE_SECONDS)

        units: Dict[str, Any] = cst.setdefault("units", {})
        for a in ads_plan:
            rec = units.get(a["key"]) or {}
            if not rec.get("adset_id"):
                fields = {"name": adset_name, "campaign_id": cst["campaign_id"],
                          "optimization_goal": m.optimization_goal,
                          "billing_event": "IMPRESSIONS", "promoted_object": m.promoted_object,
                          "targeting": spec, "status": "ACTIVE",
                          "daily_budget": DAILY_MINOR,
                          "bid_strategy": "LOWEST_COST_WITHOUT_CAP"}
                if m.regional_regulated_categories:
                    fields["regional_regulated_categories"] = m.regional_regulated_categories
                if m.regional_regulation_identities:
                    fields["regional_regulation_identities"] = m.regional_regulation_identities
                rec["adset_id"] = g.create_adset(acct, **fields)["id"]
                units[a["key"]] = rec
                persist()
                verify_expansion(g, rec["adset_id"], spec, adv, log)
                time.sleep(PACE_SECONDS)
            if not rec.get("ad_id"):
                ad = g.create_ad(acct, name=a["ad_name"], adset_id=rec["adset_id"],
                                 creative={"creative_id": creative_of[a["key"]]},
                                 status="ACTIVE", conversion_domain=conv)
                rec["ad_id"] = ad["id"]
                units[a["key"]] = rec
                persist()
                time.sleep(PACE_SECONDS)
            log.info("   %-6s adset %s ad %s · RM30/day", a["key"], rec["adset_id"], rec["ad_id"])
        built_rows.append(f"{c['key']}: campaign {cst['campaign_id']} × {len(units)} units")

    # ── 3) light verification (three edge reads, not 45 status calls) ───────────
    log.info("═" * 88)
    for c in CAMPAIGNS:
        cst = camps[c["key"]]
        info = g.get_object(cst["campaign_id"], "name,status,effective_status")
        children = g._get_all(f"{cst['campaign_id']}/adsets",
                              {"fields": "id,status,daily_budget", "limit": 100})
        n_rm30 = sum(1 for a in children if int(a.get("daily_budget") or 0) == DAILY_MINOR)
        log.info("▸ %s · %s (eff %s) · %d ad sets (%d at RM30/day)",
                 info.get("name"), info.get("status"), info.get("effective_status"),
                 len(children), n_rm30)

    final_summary(
        log, f"New Wave 0914 built PAUSED: 3 campaigns × 15 single-ad ad sets × RM30/day "
             f"= 45 chains, RM1,350/day once the operator activates the three campaigns "
             f"(ad sets and ads are ACTIVE underneath — flipping a campaign to ACTIVE "
             f"starts its 15 chains). {'; '.join(built_rows)}. 13 new creatives + the two "
             f"corrected 10,000-version Hook 1/Hook 2 creatives, shared across campaigns.")


def main() -> None:
    log = get_logger()
    try:
        build()
    except TransientGraphError as exc:
        log.error("RATE LIMITED by Meta (account call budget): %s", exc)
        log.error("State is saved — every finished upload/creative/campaign/adset/ad is "
                  "cached in %s. Re-dispatch this workflow in ~30 minutes and the build "
                  "resumes exactly where it stopped.", STATE_PATH)
        sys.exit(75)


if __name__ == "__main__":
    main()
