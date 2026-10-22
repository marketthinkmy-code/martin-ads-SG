# 操作规矩（operator 2026-10-15 批准）

这个 repo 跑 Martin 儿童长高方程式 SG 市场的 Meta 广告，账户是 SG 老户 act_1024930575770087 和 HK 账户 act_1179668409969241，所有动作都走 GitHub Actions。每次开工前先读这一页，每一条都要遵守。

## 9 条规矩

1. 测新片用 ABO，一个 ad set 只放一支片，放在 HK 账户，单支花到 RM90 还零 lead 就关（2026-10-17 起全部 SG 广告统一 RM90）。
2. 建议加预算时，每次最多加 30%，加完看满 2 天再动。
3. 复活旧片前，先看它停之前最后 7 天有没有 lead，没有就不复活。
4. 判一支片不行之前，先看它在 MY、HK、SG 老户三个账户的数据。
5. 说"哪个受众出单"时，只引用成交表上的 UTM ad set，并附上那次跑出来的数字。
6. 建任何东西之前，先给 operator 结构图，写清账户、campaign、ad set、广告、预算、受众，确认了才建。
7. 所有加总的数字都用脚本算，不心算。
8. 一律写全名不缩写，给 id 一定写上账户名。
9. 说"监控会自动处理"之前，先确认那条 campaign 名在 config/config.yaml 的 kpi.cpl_min_spend_overrides 名单上。

## 一直有效的旧规矩

- 文案先给 operator 批，批了才建。
- 不用 Claude 会话去做后台提醒、定时唤醒或盯盘，监控只靠 GitHub 上的 adbot-monitor。
- 不要动 MY 账户，除非 operator 明确要求。
- 回复用中文，先给结论，数字放进表格。
- 每周节奏：星期三直播、星期三关广告、星期四 00:00 开广告。每一场直播的报名算星期四到星期二这 6 天的广告；复盘、读数都按这个周期算（operator 2026-10-22 批准）。
- 建 SG 广告默认用自动版位（Advantage+ 版位），地区选"住在、常在、最近在新加坡"三种；定向复制好之后先过 src/adbot/sg_build_defaults.py 的 apply_sg_build_defaults()（operator 2026-10-22 批准）。
