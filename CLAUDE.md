# CLAUDE.md — Amazon Listing Management System

> AI Agent 工作规范。每次会话开始时自动加载。
> 全局规范见 `~/AGENTS.md` 和 `~/DEV_GUIDELINES.md`。

---

## 项目上下文

- **系统**: 亚马逊商品全生命周期运营管理系统
- **技术栈**: Python 3.10+ / PostgreSQL / SQLAlchemy 2.0 / Pandas
- **部署**: Docker Compose，共享 PostgreSQL (`postgres:5432`)
- **CI**: GitHub Actions self-hosted runner `amz-listing-runner-01`

---

## 关键架构约束（红线，一票否决）

- **禁止跨模块直连数据库/缓存**：模块间数据交换只通过 API / 函数调用
- **单文件 ≤ 500 行**：超过必须拆分
- **单函数 ≤ 50 行**：超过必须拆分
- **禁止硬编码配置**：所有配置通过环境变量或 `.env`

---

## 提交前强制检查清单

**每次创建 commit 前，Agent 必须在对话中显式输出以下清单并逐项确认：**

- [ ] 所有测试通过 (`pytest -q`)
- [ ] 新增/修改的 service 模块在 `docs/module-design/` 中有对应文档且已更新
- [ ] 新增 SQL 迁移在 `migrations/` 中有对应文件
- [ ] 单文件未超过 500 行红线（超过则已在本次 PR 中拆分）
- [ ] 无跨模块直连数据库/缓存
- [ ] `.env.example` 已同步新增环境变量
- [ ] 如涉及退役代码：`@retire` 标记已添加，`scheduled_removal` 日期已设

如果任一 required 项未满足又无合理跳过理由，**禁止创建 commit**。

---

## 代码退役规则

1. 迁移类任务（X → Y）必须先在 `TODO.md` 登记退役计划，使用模板 `~/templates/RETIREMENT_PLAN.md`
2. 退役 PR 必须独立于功能 PR（先跑稳新路径，再删旧路径）
3. 删除代码前执行 cleanup-check：
   - `grep -r "<module_name>" src/ --include="*.py"` 确认无 import 引用
   - `grep -r "<module_name>" config/ deploy/ --include="*.yaml" --include="*.yml" --include="*.sh"`
   - 全量 `pytest -q` 通过
   - CLI task 已从 `task_dispatcher.py` 取消注册
4. 废弃代码用 `@retire` 标记，格式见 `~/templates/RETIRE_SPEC.md`
5. 禁止在注释里写"保留为兼容"而不给 `@retire` 标记和删除日期

---

## 文档更新规则

- 新增/重构 service 模块时，必须在同一 commit 里产出/更新 `docs/module-design/<module>.md`
- README 中的 task 数量和名称必须与 `task_dispatcher.py` 一致
- 架构决策写入 `docs/decisions/`，使用 ADR 模板 `~/templates/ADR.md`
- `docs/spikes/` 不允许空目录，无内容则删除目录或补充记录

---

## 退役债务 (Retirement Debt)

当前已知退役债务（详见 `TODO.md`）：

| 退役项 | 代码量 | 目标日期 |
|--------|--------|----------|
| Excel 模板发品全链路 | ~1,173 行 + 3.1MB | 待定 |
| `template-update` CLI task | - | 待定 |
| `template-correction` CLI task | - | 待定 |
| `generate-update-file` CLI task | - | 待定 |

Agent 在处理发品相关代码时，不应在已废弃的 Excel 路径上新增功能。
