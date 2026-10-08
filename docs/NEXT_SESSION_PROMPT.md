# 下一轮任务（交给联网机器上的 coding agent）

你接手的是 Indigenous Student Funding Navigator 后端。**它已在 Windows 上从零复现并跑通，做过真实抓取，并且对其中一部分记录做过提供方官网核验**：
258 个测试通过、live 流水线 59 条真实记录（36 条已发布、1 条 `archived`）、真实服务 + smoke test、真实 `/match`。先读 `docs/HANDOFF.md`
（第 3 节"提供方页面改变了什么"、第 4 节 UBC 的决定、第 5 节已修复和未修复的问题）、`README.md`、`docs/RUNBOOK.md`、`docs/DATA_SOURCES.md`。**不要重写项目。**

## 铁律

- 不伪造执行结果；没运行过的不能写成通过。最终报告区分"实际运行 / 未运行"，附真实命令与输出摘要。
- 不通过删除、放宽或跳过测试来变绿。测试失败先当作实现问题；只有确认测试本身写错才改测试，并说明原因。
- 保持不变量：demo 数据永不进入 live 数据库或 `data/awards.jsonl`；`POST /match` 的 profile 不持久化、不写日志、不回显；
  未知永远不是 0 或"无限制"；`machine_checked` 不是人工审核（不要自行写 `human_reviewed`）；证据 quote 必须真实存在于快照文本。
- 抓取只访问 `sources.yaml` / `sources.providers.yaml` 允许的域名和路径，遵守 robots.txt；**遇到 403/429 就停下、记录、把该来源从配置里撤掉，
  不换 User-Agent、不伪装、不绕过、不重试**；`USER_AGENT` 必须带真实联系方式；不做云部署；除非用户明确要求，不推送仓库。
- Windows 上显式使用 `.venv\Scripts\python.exe`；不要直接 `import click`（Typer 新版自带实现）；`PowerShell` 里变量名不区分大小写（`$d` 与 `$D` 是同一个）。

## 任务（按优先级）

1. **复核**：`python -m venv .venv`，`pip install -r requirements.lock`，`pip install --no-deps -e .`，`pytest -q`（应 258 passed），`ruff check .`，
   `ruff format --check .`，`scripts/check_static.py`，demo 流水线两次，live 流水线两次（59 created → 59 unchanged），`serve` + `scripts/smoke_test.py`。
2. **UBC**：发出 `HANDOFF.md` 第 4 节提到的请求邮件（草稿不在仓库里，需要发件人的联系方式）。得到许可后：按许可范围抓取，或让人在浏览器里保存页面并用
   `import-snapshot` 导入（流程见 `docs/RUNBOOK.md`），再为 `ubc_award_descriptions`、`ubc_award_context` 写整理映射（带真实 quote）。
   没有许可就不碰，也不要用其他方式取得这些页面。
3. **把剩下的 ISC 目录记录升级为一手记录**（HANDOFF 第 3 节列出了已抓取但未映射的页面）：   UNBC、BC Hydro（找到真正描述该奖项的页面）、Capilano（页面由 JavaScript 渲染，文本为空：不要用无头浏览器绕过，改找静态页面或申请许可）。
   升级记录要沿用同一个 `id`（见 `data/curated/prov_*.yaml`），这样会取代目录记录；提供方页面说"暂停/停办"的用 `publication_status: archived`。
4. **站点条款**：每个来源的 `access_status` 仍是 `unreviewed`，请人逐站确认后改成 `reviewed_ok` / `restricted`。
5. **补验平台**（按你要支持的范围）：Python 3.11（锁定版本未必都支持）、Linux/macOS、可选 PostgreSQL。
6. **Indspire 捐赠方页面**：`indspirefunding.ca` 是捐赠方名单。先打开真实的捐赠方页面确认结构，再写解析器和测试；在此之前保持 `max_pages: 1`。
7. **人工审核流程**：目前没有任何记录是 `human_reviewed`。设计一个让人逐条确认解读（例如 "Open until …" 被读成已开放）的最小流程。

8. **网页应用**（`frontend/`，设计取舍见 `docs/HANDOFF.md` 第 8 节）：在 Firefox/Safari 和读屏器里验证；用工具实测配色对比度；补法语版；在 `frontend/assets/config.js` 和 `.env` 的 `USER_AGENT` 里填真实联系邮箱。改动后必须通过 `node tests/e2e/smoke.mjs`。

## 最终报告（用中文，简洁）

实际运行了什么、结果如何（真实数字）；修了哪些问题及根因；真实记录数量及来源构成（一手 / 目录）；仍未完成或需要人决定的事项；关键文件路径。
