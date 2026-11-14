# 操作规矩（operator 2026-10-15 批准）

这个 repo 跑 Martin 儿童长高方程式 SG 市场的 Meta 广告，账户是 SG 老户 act_1024930575770087 和 HK 账户 act_1179668409969241，所有动作都走 GitHub Actions。每次开工前先读这一页，每一条都要遵守。

## 死忌（operator 2026-10-26 定，不得再犯）

- 每一个建议都必须先用脚本查过数据，写清楚数字和数据来源（哪个脚本、哪个窗口），才能提出。
- 没查过的不说、不猜；还没查的要直接写"我还没查"。
- 不自己替 operator 做决定，不自作聪明；选什么片、什么受众、为什么选，都要讲清楚理由和它的成交证据。

## 9 条规矩

1. 测新片用 ABO，一个 ad set 只放一支片，放在 SG 老户（operator 2026-11-09 改，原来放 HK：11/5–11/9 SG老户 CPL RM141.69、HK RM205.89），单支花到 RM90 还零 lead 就关（2026-10-17 起全部 SG 广告统一 RM90）。
2. 建议加预算时，每次加 20%，加完看满 2 天再动（operator 2026-10-29 定，原来是最多 30%）。
3. 复活旧片前，先看它停之前最后 7 天有没有 lead，没有就不复活。
4. 判一支片不行之前，先看它在 MY、HK、SG 老户三个账户的数据。
5. 说"哪个受众出单"时，只引用成交表上的 UTM ad set，并附上那次跑出来的数字。
6. 建任何东西之前，先给 operator 结构图，写清账户、campaign、ad set、广告、预算、受众，确认了才建。
7. 所有加总的数字都用脚本算，不心算。
8. 一律写全名不缩写，给 id 一定写上账户名。
9. 说"监控会自动处理"之前，先确认那条 campaign 名在 config/config.yaml 的 kpi.cpl_min_spend_overrides 名单上。

## 一直有效的旧规矩

- 文案先给 operator 批，批了才建。
- 不用 Claude 会话去做后台提醒、定时唤醒或盯盘，监控只靠 GitHub 上的 adbot-monitor。例外：广告汇报用 Claude 定时会话「Martin SG 每日晨报」，一天 4 次（09:36 / 13:36 / 17:36 / 21:36 SGT，跑 adbot-cycle-check.yml；operator 2026-11-09 要求、照 MY 的做法，同日改成一天 4 次）。汇报只读，只汇报和提建议；关广告、改预算仍只靠 adbot-monitor 或 operator 的话。例外（operator 2026-11-10「如果碰到底线了，就立刻关」）：汇报时看到有广告已经越过监控的线（单支 RM90 零报名且 60 天内没有自己成交、campaign 零报名线、CPA 硬停 1,300）但还开着，就立刻手动跑一次 adbot-monitor.yml（dry_run false），读回它关了什么再汇报；只靠监控按规则关，不用别的方法关、不改预算。
- 建议关的线（operator 2026-11-12「花满 RM80 后 CPL 超过 RM80 就建议你关」）：本期（星期四起）花费 ≥ RM80、且本期 CPL > RM80（报名数取 Meta 和报名表较多的那个；0 报名也算超过）的广告，汇报时一看到就直接关（operator 2026-11-12 改「汇报时碰线就直接关」，理由：「把广告费降下来、CPL 降下来，一发现贵、浪费钱的广告就关掉」）：跑 adbot-pause-ads.yml（ad_ids = 这几支，sweep 0），读回状态再在汇报里写清楚关了哪几支、花费、报名；campaign 里没有在跑的广告就连 campaign 一起关。监控程式不改。60 天内有自己成交（UTM campaign + ad set + ad 都对上）的广告不套这条线，改套下面的 RM150 线，也照旧看 CPA。
- 有成交广告的关停线（operator 2026-11-14 选 B，起因：Video 2：長高了17cm 本期花 RM147.73 零报名、Hook 2：旧鞋当尺 RM135.98 一个报名，只靠 CPA 硬停要再花 6–8 天才会关，operator 同日先手动叫关这两支）：60 天内有自己成交的广告，本期（星期四起）花费 ≥ RM150、且本期 CPL > RM150（报名数取 Meta 和报名表较多的那个；0 报名也算超过），汇报时一看到就直接关，做法同上面的 RM80 线（adbot-pause-ads.yml，读回再汇报，campaign 没有在跑的广告就一起关）。RM150 约是这两支以前正常 CPL（RM60–102）的 1.5–2.5 倍。CPA 硬停 1,300 照旧。监控程式不改。注意：止损线只开 60 天内有成交的广告，这类广告被关后，11/19 起可能没有广告能开，要 operator 另外决定。
- 建议不能只看 CPL（operator 2026-11-13「我希望你的分析建议基准也有 CPA，不要只是看 CPL，我的结果还是整体项目的 ROAS，赚不赚钱」）：每个建议都要同时写单支广告的 CPA / ROAS（60 天自己成交）和 SG 整体项目的 ROAS、赚 / 亏（SG老户 + HK 全部花费 vs 成交表 UTM 对上 SG 的营收，无 UTM 成交另列不算进 SG）。整体数字用 scripts/sg_roas_1113.py（workflow adbot-sg-roas.yml，只读，按直播周和 30 / 60 / 90 天）。
- 止损线（operator 2026-11-13 选 A）：如果 2026-11-18 直播 SG 0 成交（成交表 UTM 对上 SG老户 / HK、日期 11/12–11/18，用 adbot-sg-roas.yml 读），11/19 起的新一期只开 60 天内有自己成交（UTM campaign + ad set + ad 都对上）的广告，其他没有成交记录的广告先不开、已开的关掉；先找直播 / 跟进成交的问题，operator 说可以再放钱才开别的。成交表还没更新 11/18 的成交时先问 operator，不能当 0 单处理。
- 不要动 MY 账户，除非 operator 明确要求。
- 监控的 RM90 零报名线只放过最近 60 天内有自己成交（UTM campaign + ad set + ad 都对上）的广告；成交在 60 天前的旧卖家照样会被关。重开旧片前要先讲清楚这一点（operator 2026-11-07 选 A，维持不改）。
- 关广告时，campaign 里没有在跑的广告了，就连 campaign 一起关；不要留 ad / ad set 关了但 campaign 还开着（operator 2026-10-29 定；监控和 scripts/pause_ads_1029.py 都会这样做）。
- 回复用中文，先给结论，数字放进表格。
- 每周节奏：星期三直播、星期三关广告、星期四 00:00 开广告。每一场直播的报名算星期四到星期二这 6 天的广告；复盘、读数都按这个周期算（operator 2026-10-22 批准）。星期三关广告由 operator 手动做；adbot-weekly-off.yml 的自动定时已拿走（operator 2026-11-12「weekly off 拿走这个指令」，原因是 11/11 它迟了 8 小时、23:05 才跑，关掉了等 00:00 开始的新 campaign），只剩手动触发；adbot-weekly-on.yml 照旧，只开回带 weekly-off 标签的广告。
- 建 SG 广告默认用自动版位（Advantage+ 版位），地区选"住在、常在、最近在新加坡"三种；定向复制好之后先过 src/adbot/sg_build_defaults.py 的 apply_sg_build_defaults()（operator 2026-10-22 批准）。

## 下一场 Webinar 分析重点（operator 2026-11-12，Phase 3 已验收）

- 停止修改 Lead Quality 分析脚本和评分规则；11/11 Phase 3 不再重跑，结果存在 docs/baseline_webinar_nov11.md，作为 11/18 对比基准。
- 2026-11-18 Webinar 分析比较：(1) Campaign / Ad 真实 CPL、Show-Up、CPA、ROAS；(2) 早报名 vs 最后 48 小时报名的 Show-Up Rate（SG 特别关注临近开课报名者的出席）；(3) First-time vs Returning 的出席与成交；(4) Survey Completed、Qualified、Core ICP 只作辅助指标，不参与预算调整。
- 未填 Survey 的家长不得判定为低质量。原有 Meta Ads 监控和预算管理标准照旧；不改 GHL、Google Sheet、预算或自动化。

## Lead Quality 统计规则（operator 2026-11-06 最终确认）

数据：Register 分页，G=报名日期、H=source、J/K/L=UTM campaign / ad set / ad、P–T=问卷 Q1–Q5、U=Martin Lead Quality Score（GHL 已算好，不重算）。脚本 scripts/lead_quality_1106.py（workflow adbot-lead-quality.yml，手动、只读）。

1. 所有 Lead Quality 报告一律用 G 栏报名日期；不需要、也不新增问卷提交时间栏。
2. 家长隔几天才做问卷，分数仍算回原本的报名日期；每日分析按报名日期读最新评分状态。
3. Survey Completion Rate = 同一报名批次已完成问卷人数 ÷ 该批次有效报名人数。
4. Qualified Lead Rate = 同一报名批次 Score ≥70 人数 ÷ 该批次有效报名人数。
5. CPQL = 同市场（SG老户 + HK）、同广告归因范围（同 campaign / ad set / ad 名字）、同报名日期区间的花费 ÷ Qualified 人数。
6. 还没做问卷的一律标 Pending，不算低质量。
7. 分级：A 85–100、B 70–84、C 50–69、D 0–49；Core ICP = 总分 ≥70 且 Q2 ≥20 且 Q5 ≥16（Q2 / Q5 由原始答案对表算）。对表一律用 GHL 的真实选项全文，不用关键词（operator 2026-11-10）：
   - Q2：「有记录孩子身高，发现最近长高速度明显变慢」25；「曾经带孩子做成长评估，希望进一步了解或改善」25；「孩子明显比同龄人矮，担心差距越来越大」20；「不确定孩子目前的成长情况是否正常」12；「只是提前学习」5（GHL 原文还没在表上出现过）。
   - Q5：「希望有专业人士了解孩子的情况，给予适合的指导，并持续跟进」20；「希望有一套清楚的方法，可以跟着步骤帮助孩子改善生活习惯」16（= 系统性方法、按步骤执行）；「希望先了解孩子成长的关键因素，再决定下一步」10；「主要想获得一些免费的成长知识和建议」4。
   - 对不上的答案标 `UNMAPPED / NEEDS REVIEW`，不能自动判成"不是 Core ICP"。总分仍用 GHL 的 U 栏，不重算、不改。
   - 同一人（姓名 + 电邮 + 电话）之前有更早报名日期的 = Returning Lead：这次报名的 UTM 归因照算，但 First-time 和 Returning 分开数，重新报名不等于首次获客。
   - SG 合计和每日的 CPQL 用 SG老户 + HK 全部花费，标 Blended，不能跟单支广告的 Preliminary CPQL 比。
8. 只算验证过的 SG 报名（UTM 对上 SG老户 / HK 的 campaign）；[MY]、MY 户口、无 UTM、来源不明的单独列，不归入 SG；ad 名字不能单独用来归因。MY 与 SG 分开，不混预算或币种。
9. 不改 Google Sheet、GHL Workflow、广告自动化，不新增字段。
10. 问卷分析暂定从 2026-11-06 起算（不代表 11/6 报名的人都收到邀请）。之前报名、又没有答案的 = Pre-launch Registration / Invitation Unknown，没有发送记录不能说 Not Invited，也不算拒绝填写，不进任何比率分母；起始日后还没做的 = Eligible Pending（operator 2026-11-06 定）。
11. 没有 UTM 的问卷记录不代表问卷弄丢了 UTM；没有证据不判定 tracking error，先看带真实广告 UTM 的报名做完问卷后 campaign / ad set / ad 是否还在。
12. Qualified > 0 就算 Preliminary CPQL = 对上的 Meta 花费 ÷ Qualified；Qualified = 0 时 CPQL = N/A（不写 RM0，也不判广告差）。样本少时标 PRELIMINARY / INSUFFICIENT DATA；统计可计算性和预算决策可靠性分开写。不能只凭问卷分数 SCALE / REDUCE / PAUSE，原有 CPL / CPA / 花费规则、每小时监控、预算建议照旧。Meta 花费要确认户口结算币种（SG老户、HK 都是 MYR），市场与币种一致。
13. 每个报名批次都要列：原始报名笔数、去重人数（同一报名日期 + 同一人算 1 人）、Valid Registrations、Survey Completed、Completion Rate、Score Coverage Rate、Pending、Qualified（≥70）÷ Valid 和 ÷ Completed（两个分母不同）、Core ICP；最近 3 天的批次标"数据未成熟"。
