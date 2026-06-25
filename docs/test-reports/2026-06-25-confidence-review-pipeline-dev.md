# Confidence Review Pipeline 开发验收报告

- 日期：2026-06-25
- 范围：Evidence-grounded required LLM attribute review pipeline
- 状态：已完成生产部署与验收

## 改造内容

1. 新增 `ConfidenceScorer` 与 `config/listing_gates/review_policy.yaml`，默认先对白名单 `CHAIR` 灰度启用。
2. `AttributeResolver` 支持 `overrides`，required LLM 属性不再在 resolver 内硬写 `blocking=True`，而是输出 `review_status`、`review_route`、`confidence_score`、`review_context`。
3. `AmazonListingAttributeCoverageGate` 只放行 `auto_approved` / `completed` 的 required LLM 属性；未审核属性返回 `NEEDS_REVIEW_REQUIRED_ATTRIBUTE`。
4. 新增 `amz_listing_pending_review` migration、repository、`ReviewManager`、`AttributeReviewAgent`、`AttributeReviewPlanRouter`，支持 pending 落库、AI evidence 字面复核、completed plan snapshot 提交。
5. 新增 CLI：`review-pending-attributes`、`submit-reviewed-plans`。

## 验收命令

```bash
.venv/bin/pytest -q tests/unit/services/test_confidence_scorer.py tests/unit/services/test_attribute_resolver.py tests/unit/services/test_amazon_listing_attribute_coverage_gate.py tests/unit/services/test_review_manager.py tests/unit/services/test_product_listing_api_plan_builder.py tests/unit/cli/test_task_dispatcher.py tests/integration/repositories/test_amazon_listing_pending_review_repository_sql_contract.py
```

结果：48 passed。

```bash
.venv/bin/pytest -q tests/unit/services/test_amazon_listing_payload_builder.py tests/unit/services/test_product_listing_service.py tests/unit/cli/test_operation_handlers.py
```

结果：56 passed。

```bash
.venv/bin/alembic upgrade head --sql >/tmp/amz_listing_alembic_head.sql
```

结果：成功生成至 `010_amz_listing_pending_review`。

```bash
.venv/bin/ruff check src/services/confidence_scorer.py src/services/review_manager.py src/services/attribute_review_agent.py src/services/attribute_review_plan_router.py src/repositories/amazon_listing_pending_review_repository.py src/services/attribute_resolver.py src/services/amazon_listing_attribute_coverage_gate.py src/services/product_listing_api_plan_builder.py src/cli/task_dispatcher.py tests/unit/services/test_confidence_scorer.py tests/unit/services/test_review_manager.py tests/integration/repositories/test_amazon_listing_pending_review_repository_sql_contract.py
```

结果：All checks passed。

```bash
.venv/bin/pytest -q
```

结果：全量通过。

```bash
git diff --check
```

结果：通过。

## Code Review 后补充验证

```bash
.venv/bin/pytest -q tests/unit/services/test_confidence_scorer.py tests/unit/services/test_attribute_resolver.py tests/unit/services/test_amazon_listing_attribute_coverage_gate.py tests/unit/services/test_review_manager.py tests/unit/services/test_product_listing_api_plan_builder.py tests/unit/cli/test_task_dispatcher.py tests/integration/repositories/test_amazon_listing_pending_review_repository_sql_contract.py --cov=src.services.confidence_scorer --cov=src.services.review_manager --cov=src.services.attribute_review_agent --cov=src.services.attribute_review_plan_router --cov=src.repositories.amazon_listing_pending_review_repository --cov-report=term-missing
```

结果：51 passed；新模块覆盖率 repository 96% / scorer 87% / plan_router 81% / review_manager 80%，总 85%。

```bash
.venv/bin/ruff check <confidence-review-pipeline changed files>
.venv/bin/pytest -q tests/unit tests/integration
```

结果：ruff All checks passed；全量 unit + integration 回归通过。

## 生产部署与验收

```bash
bash deploy/production/deploy.sh
docker compose -f /data/docker-compose/amz-listing-management-system/docker-compose.yml exec -T amz-listing-management-system alembic upgrade head
```

结果：镜像升级为 `amz-listing-management-system:2026-06-25-confidence-review-pipeline`；主容器与 3 个 scheduler 均使用新 tag，主容器 healthy；Alembic 升级到 `010_amz_listing_pending_review`，`amz_listing_pending_review` 表存在。

生产 smoke：

- 公网 `https://amz-listing.meowy.fans` 返回 SSO 302。
- `list-categories` 正常返回 16 个品类。
- `review-pending-attributes --category CHAIR` 正常，当前 rows=0。
- `submit-reviewed-plans --category CHAIR` dry-run 正常，当前提交 0 个 reviewed plan。
- CHAIR 单 SKU `meow2511081Gqqd` dry-run：LLM attribute extraction 成功调用 Qwen，多项 required LLM 提取无 JSON 解析失败；最终仍因真实非审核类属性缺口返回 `blocked_attribute_coverage`，未 PUT，fail-closed 保持。
- 使用临时 smoke review 记录验证 pending review 闭环：落库 -> `AttributeReviewAgent` 审核 -> `completed` -> 清理，清理后残留 0 条。
- 部署后主容器 5 分钟内无 `JSON解析失败` / `无效JSON响应` / `Traceback` / `ERROR` / `CRITICAL`。

## 已知事项

- `ruff check src/cli/operation_handlers.py` 会命中历史遗留的 F541/F841，非本次新增代码引入；本次仅对新增与核心改造文件做定向 ruff。
- 当前人工录入入口仍属后续 P4 scope；含 `needs_human` 的记录会停留在 `in_progress`，等待人工决策写入后再提交 reviewed plan。
