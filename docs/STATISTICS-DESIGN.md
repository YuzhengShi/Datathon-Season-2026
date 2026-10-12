# Statistics v6 — 图型与界面升级

v6 把 Statistics 从重复的柱状图卡片，升级为按分析任务组织的数据报告，并与 live 版本已有的全国地图、地区排名和来源面板合并。本文说明页面结构、图型选择、数据语义和验证范围。

## 页面结构与阅读顺序

KPI 之后是 12 栏网格（窄屏逐步折叠为单栏），按分析任务分组：

1. **地理**：01 地图（朝北；Regional / Incl. national，Map / Tiles 两种视图，悬停卡片）；02 地区排名（每个地区的区域记录数，按来源拆成 provider page 与 federal directory）。
2. **构成与金额**：03 环形图（奖学金 / program，加上“全国 / 区域 / 未写地区”三个桶）；04 金额分布（Curve / Share / Dots 三个视图，下方是三个金额区间的筛选标签）。
3. **交叉、来源、受众与时间**：05 热力矩阵（地区 × 社区）；06 提供方树图（另列前 5 名，完整列表收在 “View … providers” 里）；07 社区径向图；08 申请时间 waffle 方块图。
4. **数据来源**：09 来源构成（provider page / federal directory）；10 来源新鲜度（来源页面最后修改的年份）。
5. **项目明细**：完整表格（默认 40 行，可展开全部）、CSV 导出和计数规则。

所有图都与筛选联动：点击地图区域、排名行、热力格、树图矩形、径向环或方块即筛选，再点一次取消。金额曲线底部和散点的实际数据标记可打开项目详情。

## 图型选择与指标

| 图型 | 回答的问题 | 数据含义与交互 |
| --- | --- | --- |
| 加拿大分区地图 / Tiles | 支持在哪里？ | 颜色只表示区域项目数，全国项目不涂到任何地区；点击区域筛选 |
| 地区排名 | 哪些地区记录最多？ | 13 个地区按区域记录数排序，条形按来源类型拆分 |
| 环形图 + 三个桶 | 奖学金与 program 占比如何？ | 互斥类别；全国 / 区域 / 未写地区三者相加等于总数 |
| 平滑分布曲线 + 面积 | 已列出的金额集中在哪里？ | 从实际金额计算 Gaussian KDE；基线标记为实际项目；属于估计分布 |
| 累计占比曲线 | 多少项目的已列金额不高于某个值？ | 精确经验累计分布；相同金额合并计数；悬停显示阈值与分母 |
| 分组散点 / strip plot | 每一个项目列了多少钱？ | 奖学金与 program 分行；三角形表示 cap；点击或键盘打开详情 |
| 地区 × 社区热力矩阵 | 哪些地区有某个社区的支持？ | 每格是覆盖该地区、该社区的唯一项目数（全国项目计入每个地区）；点击同时选择两个条件 |
| 提供方矩形树图 | 哪些提供方贡献较多项目？ | 面积表示项目数占比；最多展示 11 家与“其余”一组；前 5 名与完整列表另列 |
| 社区径向小图 | 某社区能触达多少项目？ | 分母为当前选中项目数；社区之间重叠，百分比不能相加 |
| 时间类型 waffle 方块图 | 申请时间通常如何确定？ | 100 条以内一格一条；更大选择使用 100 格并按最大余数分配，图例保留精确数量 |
| 来源构成 / 来源新鲜度 | 记录从哪里来、有多新？ | provider page 与 federal directory；页面最后修改年份，未写日期单列 |

没有人为生成时间趋势。金额横轴使用 `log1p` 间距，让小额与较大 cap 能同时阅读。Curve 的纵轴是相对估计集中程度，既不是获批概率，也不是历史增长；单个已列金额时自动展示累计占比。Share 保留不平滑的经验分布。

## 数据语义（live 数据下的规则）

- **金额**：曲线、累计曲线、散点和中位数只使用非负 CAD 已列金额（包含 cap），排除 pool total、已声明的区间（`amount` 为 null）、其他货币和未知金额；不把这些数值求和当作实际发放资金。live 数据中目前是 529 条里 257 条。
- **地区**：热力矩阵中，全国项目计入每个地区；来源没有写地区的记录（`province` 为 null）不在任何格子里，但在筛选视图里按“保留未写明的细节”处理，与地图一致。
- **申请时间**：每种 `deadline_kind`（`date`、`annual_rule`、`rolling`、`local_administrator`、`unspecified`）都有名称和颜色，未知取值显示为 “Other timing”。当某类只有 1 条而选择超过 100 条时，它按四舍五入分不到方块，只出现在图例里（图例数字始终精确）。
- **提供方**：live 数据有 300 多个提供方，多数只有 1 条记录，所以树图里“其余”会占大部分面积；因此另列前 5 名，完整列表在树图下方展开。
- 小样本只产生粗略估计；方法说明收在页面的 “Data quality & counting rules” 中。

## 后端接口

`POST /api/statistics` 的 `amount_rows` 新增 `province`、`community`、`type` 三个字段（`province` 为 null 表示来源没有写地区），使热力矩阵和项目散点可以直接使用后端的同一批记录。已有字段与筛选接口保持兼容；旧响应没有这三个字段时，前端按项目 ID 从 `dist/data/opportunities.json` 的记录恢复。静态托管（没有后端）时，全部在浏览器里用同一份数据计算。

## 文件

| 文件 | 内容 |
| --- | --- |
| `dist/charts.js` | 分布、热力、树图、径向、waffle 的 SVG/HTML 生成与统计计算（无构建、无依赖） |
| `dist/insights.js` / `dist/insights.css` / `dist/index.html` | 页面、联动、提示框和样式 |
| `src/navigator/app/services.py` | `amount_rows` 的新增字段 |
| `scripts/qa-charts.cjs`、`tests/js/charts.test.mjs` | 统计计算检查（10 项）；pytest 通过后者运行前者 |
| `scripts/qa-ui.cjs` | DOM 交互检查（63 项，含 529 条合成记录的 QA 夹具；夹具只在测试里，不写入产品数据） |
| `tests/e2e/site.mjs` | 真实 Chrome 检查（桌面 1280 px、手机 390 px，共 51 项：Statistics 页 37 项，聊天窗口 14 项），包括图表绘制、提示框位置和聊天布局 |

## 验证范围

已验证：Node 与 jsdom 的计算和交互检查；真实 Chrome（桌面 1280 px 与手机 390 px）的 51 项检查，覆盖地图数字、报告图表、提示框位置、聊天窗口布局、无横向滚动与无 JavaScript 错误。未验证：Firefox、Safari、屏幕阅读器和颜色对比度的实际测量。

## 研究参考

以下官方资料提供图型用途；本页的颜色、布局、图型组合与交互是本项目的设计选择。

- [Metabase：Which chart should you use?](https://www.metabase.com/learn/metabase-basics/querying-and-dashboards/visualization/chart-guide)：按趋势、关系和构成区分图型；散点与气泡表达多个数值维度，少量类别可用 donut。
- [Power BI：Visualizations overview](https://learn.microsoft.com/en-us/power-bi/visuals/power-bi-visualizations-overview)：线与面积、组合图、树图、散点、矩阵、地图、KPI 及 slicer 的用途。
- [Tableau：Choose the Right Chart Type](https://help.tableau.com/current/pro/desktop/en-us/what_chart_example.htm)：按比较、分布、相关性与空间问题选图。
- [R stats：Bandwidth Selectors](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/bandwidth.html)：Gaussian KDE 的 normal-reference 带宽。本实现对 `log1p` 金额使用 0.9 × min(SD, IQR / 1.34) × n^(-1/5)，并加入有限的带宽下限和相同值回退。

后续数据充足时还适合：有真实快照日期的多线趋势与面积图、有可比金额单位的箱线图、有真实申请阶段的漏斗图、有明确流量定义的 Sankey、有真实截止日期的日历热力图、以及同时具备三个数值维度的气泡散点。当前版本优先实现现有字段可以支持的图型。
