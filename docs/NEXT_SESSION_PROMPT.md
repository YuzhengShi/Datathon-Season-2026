# 下一轮任务（交给联网机器上的 coding agent）

你接手的是一个已经写好、但**其中一部分从未被运行过**的后端项目 Indigenous Student Funding Navigator。先读
`docs/HANDOFF.md`（哪些跑过、哪些没跑）、`README.md`、`docs/RUNBOOK.md`、`docs/DATA_SOURCES.md`、`docs/DATA_MODEL.md`。
**不要重写项目。本轮的任务是验证并修复，然后才是取真实数据。**

## 铁律

- 不伪造执行结果；没有运行过的东西不能写成通过。最终报告逐项区分"实际运行 / 未运行"，附真实命令与输出摘要。
- 不通过删除、放宽或跳过测试来让它变绿。测试失败先当作实现问题修；只有确认是测试本身写错时才改测试，并说明原因。
- 保持这些不变量：demo 数据永不进入 live 数据库或 `data/awards.jsonl`；`POST /match` 的 profile 不持久化、不写日志、不回显；
  未知永远不是 0 或"无限制"；`machine_checked` 不是人工审核（不要自行写 `human_reviewed`）；证据 quote 必须真实存在于快照文本。
- 不做云部署、不推送仓库、不修改任何远程数据库。
- 抓取只访问 `sources.yaml` 允许的域名和路径；读取并遵守 robots.txt；在 `.env` 里把 `USER_AGENT` 设成带联系方式的值；
  不绕过登录、验证码或访问限制；遇到 429/403 就停下并记录，不要加大并发。

## 任务（按顺序）

1. **环境**：`python -m venv .venv`，激活，`python -m pip install -r requirements.lock`，`python -m pip install --no-deps -e .`。
   记录实际装到的版本。
2. **先跑从未执行过的三个套件**：`python -m pytest -q tests/test_db.py tests/test_api.py tests/test_cli.py`。
   这些测试覆盖 SQLAlchemy 仓库、Alembic 迁移、FastAPI 路由、Typer 命令行。逐个修复失败；预期会有小问题
   （类型注解、Typer/Click 版本、SQLAlchemy 映射细节）。每个修复写清根因。
3. **全量检查**：`python -m pytest -q`（除"需要 jsonschema 的交叉检查"外不应再有跳过）；
   `python -m ruff format .` 然后 `python -m ruff check .` 和 `python -m ruff format --check .`；
   `python scripts/check_static.py`；`python scripts/freeze_lock.py`（把范围版本换成精确锁定）。
4. **demo 全链路**：`python -m navigator.cli pipeline --mode demo --as-of 2026-10-07`；再运行一次确认全部 `unchanged`；
   终端 1 `python -m navigator.cli serve --mode demo --host 127.0.0.1 --port 8000`，终端 2
   `python scripts/smoke_test.py --base-url http://127.0.0.1:8000 --expect-mode demo`。
   另外用 `examples/requests/*.json` 手动 POST `/match`，确认三段演示的结果与 `examples/expected/` 一致。
5. **更新 `docs/HANDOFF.md`**：只改你**亲自验证过**的验收行，并运行 `python scripts/refresh_handoff_counts.py`。提交。

## 之后的 live 阶段（第 6 步开始需要人确认）

6. **先停下来问人**：列出 `sources.yaml` 每个来源的站点条款链接，请人确认可以抓取；把确认过的来源改成 `reviewed_ok`，
   不允许的改成 `restricted`。没有确认就不要做第 7 步。
7. `python -m navigator.cli fetch --mode live --sources sources.yaml --max-pages 50`，读 `data/runs/<run>.json`
   （robots、失败、待核实）。**打开真实快照**，逐个对照适配器的假设（ISC 表格列与分页、UBC 奖项标题层级、Indspire 列表/详情页）。
   适配器与真实页面不符时，改适配器并补一个用真实页面片段做成的小夹具测试（只放必要片段）。
8. `python -m navigator.cli extract --mode live`，读 `data/discovery/*.summary.json`（ISC 声明数量、实际读到的行数、覆盖率、
   分页是否完整——538 只是历史观察，不是目标）。
9. 为 SFU、MNBC、ISC 渠道页写 `data/curated/<source_id>.yaml`（格式见 `data/curated/README.md`）：每条事实都带真实 quote；
   拨款机构条件放 `funder_conditions`；页面与政策/年度指南互相矛盾时用 `conflicts`，不要自己挑一个答案；
   当地管理员决定的规则保持 `unknown` 并保留联系路径。
10. `python -m navigator.cli pipeline --mode live --limit 30 --max-pages 50 --resume`，目标 20–30 条**不同的真实机会**，
    尽量覆盖至少三个不同的申请管理机构（Indspire 的捐赠人不算管理机构）。数量不够就如实报告差额和每个来源的失败原因，
    **绝不用 demo 数据补足**。

## 最终报告（用中文，简洁）

实际运行了什么、结果如何（真实数字）；修了哪些问题及根因；真实机会数量 / 目标差额 / 每个来源的状态；仍未完成或需要人决定的事项；
关键文件路径。不要写"你接下来可以……"来代替本轮已授权的工作。
