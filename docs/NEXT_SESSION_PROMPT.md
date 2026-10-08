# 下一轮任务（交给联网机器上的 coding agent）

你接手的是 Indigenous Student Funding Navigator 后端。**它已经在一台 Windows 机器上从零复现并跑通，并且做过一次真实抓取**：
241 个测试通过、demo 全链路、live 流水线产出 33 条真实记录、真实服务 + smoke test。先读 `docs/HANDOFF.md`（第 3 节是真实页面的发现，
第 4 节是已修复和未修复的问题）、`README.md`、`docs/RUNBOOK.md`、`docs/DATA_SOURCES.md`。**不要重写项目。**

## 铁律

- 不伪造执行结果；没运行过的不能写成通过。最终报告区分"实际运行 / 未运行"，附真实命令与输出摘要。
- 不通过删除、放宽或跳过测试来变绿。测试失败先当作实现问题；只有确认测试本身写错才改测试，并说明原因。
- 保持不变量：demo 数据永不进入 live 数据库或 `data/awards.jsonl`；`POST /match` 的 profile 不持久化、不写日志、不回显；
  未知永远不是 0 或"无限制"；`machine_checked` 不是人工审核（不要自行写 `human_reviewed`）；证据 quote 必须真实存在于快照文本。
- 抓取只访问 `sources.yaml` 允许的域名和路径，遵守 robots.txt；**遇到 403/429 就停下记录，不换 User-Agent、不伪装、不绕过**；
  `USER_AGENT` 必须带真实联系方式；不做云部署、不推送仓库。
- Windows 上显式使用 `.venv\Scripts\python.exe`；不要直接 `import click`（Typer 新版自带实现）。

## 任务（按优先级）

1. **复核**：`python -m venv .venv`，`pip install -r requirements.lock`，`pip install --no-deps -e .`，`pytest -q`（应 241 passed），
   `ruff check .`，`ruff format --check .`，`scripts/check_static.py`，demo 流水线两次，`serve` + `scripts/smoke_test.py`。
2. **站点条款**：`sources.yaml` 的 `access_status` 仍是 `unreviewed`。请人逐站确认条款后改成 `reviewed_ok` / `restricted`。
3. **UBC**（`students.ubc.ca` 两个页面返回 HTTP 403）：不要绕过。方案由人决定：联系 UBC 申请许可或数据源；或由人用浏览器手动保存页面，
   再实现"手动快照导入"（必须记录来源 URL、保存时间和哈希，证据校验照常进行）。
4. **把 ISC 目录记录升级为一手记录**：25 条来自 ISC 目录（页面有各自的 "Date modified"，其中 11 条是 2022 年），没有截止日期、资格条件只是自由文本。
   对每条到提供方官网（记录里 `application.url`）取当期页面，写 `data/curated/*.yaml`，补截止日期、结构化规则和金额，带真实 quote。
5. **为这些页面写整理映射**（HANDOFF 第 3 节：已抓取但尚无映射）：`isc_psssp`、`isc_inuit_strategy`、`isc_metis_strategy`、`mnbc_steps`、`indspire_apply_now`
   （只作申请政策上下文）。拨款机构条件放 `funder_conditions`；互相矛盾的官方说法用 `conflicts`；本地管理员决定的规则保持 `unknown`。
6. **Indspire 捐赠方页面**：`indspirefunding.ca` 是捐赠方名单，不是奖项名单。先打开真实的捐赠方页面确认结构，再写解析器和测试；
   在此之前保持 `max_pages: 1`，不要放开。
7. **补验平台**（按你要支持的范围）：Python 3.11（锁定版本未必都支持）、Linux/macOS、可选 PostgreSQL。
8. **已知未修复**：同一运行编号重跑会残留旧的 `data/quarantine/<run_id>.jsonl`（流水线每个运行编号会写两次，不能在 `write_quarantine` 里清理；
   应在运行开始时清理）。

## 最终报告（用中文，简洁）

实际运行了什么、结果如何（真实数字）；修了哪些问题及根因；真实记录数量及来源构成；仍未完成或需要人决定的事项；关键文件路径。
