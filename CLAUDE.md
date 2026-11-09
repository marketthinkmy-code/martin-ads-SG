# 操作规矩（operator 2026-10-15 批准）

这个 repo 跑 Martin 儿童长高方程式 SG 市场的 Meta 广告，账户是 SG 老户 act_1024930575770087 和 HK 账户 act_1179668409969241，所有动作都走 GitHub Actions。每次开工前先读这一页，每一条都要遵守。

## 死忌（operator 2026-10-26 定，不得再犯）

- 每一个建议都必须先用脚本查过数据，写清楚数字和数据来源（哪个脚本、哪个窗口），才能提出。
- 没查过的不说、不猜；还没查的要直接写"我还没查"。
- 不自己替 operator 做决定，不自作聪明；选什么片、什么受众、为什么选，都要讲清楚理由和它的成交证据。

## 9 条规矩

1. 测新片用 ABO，一个 ad set 只放一支片，放在 HK 账户，单支花到 RM90 还零 lead 就关（2026-10-17 起全部 SG 广告统一 RM90）。
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
- 不用 Claude 会话去做后台提醒、定时唤醒或盯盘，监控只靠 GitHub 上的 adbot-monitor。例外：每天早上的广告晨报用 Claude 定时会话「Martin SG 每日晨报」（每天 09:36 SGT，跑 adbot-cycle-check.yml；operator 2026-11-09 要求、照 MY 的做法）。晨报只读，只汇报和提建议；关广告、改预算仍只靠 adbot-monitor 或 operator 的话。
- 不要动 MY 账户，除非 operator 明确要求。
- 监控的 RM90 零报名线只放过最近 60 天内有自己成交（UTM campaign + ad set + ad 都对上）的广告；成交在 60 天前的旧卖家照样会被关。重开旧片前要先讲清楚这一点（operator 2026-11-07 选 A，维持不改）。
- 关广告时，campaign 里没有在跑的广告了，就连 campaign 一起关；不要留 ad / ad set 关了但 campaign 还开着（operator 2026-10-29 定；监控和 scripts/pause_ads_1029.py 都会这样做）。
- 回复用中文，先给结论，数字放进表格。
- 每周节奏：星期三直播、星期三关广告、星期四 00:00 开广告。每一场直播的报名算星期四到星期二这 6 天的广告；复盘、读数都按这个周期算（operator 2026-10-22 批准）。
- 建 SG 广告默认用自动版位（Advantage+ 版位），地区选"住在、常在、最近在新加坡"三种；定向复制好之后先过 src/adbot/sg_build_defaults.py 的 apply_sg_build_defaults()（operator 2026-10-22 批准）。

## Lead Quality 统计规则（operator 2026-11-06 最终确认）

数据：Register 分页，G=报名日期、H=source、J/K/L=UTM campaign / ad set / ad、P–T=问卷 Q1–Q5、U=Martin Lead Quality Score（GHL 已算好，不重算）。脚本 scripts/lead_quality_1106.py（workflow adbot-lead-quality.yml，手动、只读）。

1. 所有 Lead Quality 报告一律用 G 栏报名日期；不需要、也不新增问卷提交时间栏。
2. 家长隔几天才做问卷，分数仍算回原本的报名日期；每日分析按报名日期读最新评分状态。
3. Survey Completion Rate = 同一报名批次已完成问卷人数 ÷ 该批次有效报名人数。
4. Qualified Lead Rate = 同一报名批次 Score ≥70 人数 ÷ 该批次有效报名人数。
5. CPQL = 同市场（SG老户 + HK）、同广告归因范围（同 campaign / ad set / ad 名字）、同报名日期区间的花费 ÷ Qualified 人数。
6. 还没做问卷的一律标 Pending，不算低质量。
7. 分级：A 85–100、B 70–84、C 50–69、D 0–49；Core ICP = 总分 ≥70 且 Q2 ≥20 且 Q5 ≥16（Q2 / Q5 由原始答案对表算）。
8. 只算验证过的 SG 报名（UTM 对上 SG老户 / HK 的 campaign）；[MY]、MY 户口、无 UTM、来源不明的单独列，不归入 SG；ad 名字不能单独用来归因。MY 与 SG 分开，不混预算或币种。
9. 不改 Google Sheet、GHL Workflow、广告自动化，不新增字段。
10. 问卷分析暂定从 2026-11-06 起算（不代表 11/6 报名的人都收到邀请）。之前报名、又没有答案的 = Pre-launch Registration / Invitation Unknown，没有发送记录不能说 Not Invited，也不算拒绝填写，不进任何比率分母；起始日后还没做的 = Eligible Pending（operator 2026-11-06 定）。
11. 没有 UTM 的问卷记录不代表问卷弄丢了 UTM；没有证据不判定 tracking error，先看带真实广告 UTM 的报名做完问卷后 campaign / ad set / ad 是否还在。
12. Qualified > 0 就算 Preliminary CPQL = 对上的 Meta 花费 ÷ Qualified；Qualified = 0 时 CPQL = N/A（不写 RM0，也不判广告差）。样本少时标 PRELIMINARY / INSUFFICIENT DATA；统计可计算性和预算决策可靠性分开写。不能只凭问卷分数 SCALE / REDUCE / PAUSE，原有 CPL / CPA / 花费规则、每小时监控、预算建议照旧。Meta 花费要确认户口结算币种（SG老户、HK 都是 MYR），市场与币种一致。
13. 每个报名批次都要列：原始报名笔数、去重人数（同一报名日期 + 同一人算 1 人）、Valid Registrations、Survey Completed、Completion Rate、Score Coverage Rate、Pending、Qualified（≥70）÷ Valid 和 ÷ Completed（两个分母不同）、Core ICP；最近 3 天的批次标"数据未成熟"。
