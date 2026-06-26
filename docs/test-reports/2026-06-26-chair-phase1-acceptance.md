# EPIC-AMZ-LISTING-REQUIREMENT-PAYLOAD-V2 — Phase 1 Acceptance 实证

- 日期：2026-06-26
- 范围：Phase 1 (S0–S3) read-only RequirementTree 对 CHAIR 单 SKU 的验收
- 状态：通过
- 关联：
  - Epic：`docs/epics/listing-requirement-payload-engine-v2.md`
  - ADR：`docs/decisions/ADR-2026-06-26-listing-requirement-payload-engine-v2.md`
  - 模块设计：`docs/module-design/listing-requirement-payload-engine-v2.md`
  - TASK：`TASK-145`

## 1. 验收命令

```bash
docker exec amz-listing-management-system printenv DATABASE_PASSWORD   # 取容器内 DB 凭证
# 宿主机直跑（V2 代码未进生产镜像 2026-06-15，需用源码 + 容器 DB IP）
DATABASE_HOST=172.20.0.29 DATABASE_PORT=5432 DATABASE_NAME=amz_listing \
DATABASE_USER=amz_listing DATABASE_PASSWORD=<from-container> \
  python3 main.py --task analyze-listing-requirements-v2 \
    --category CHAIR --sku meow2511081Gqqd
```

运行环境：
- 源码：`~/amz_listing_management_system`（V2 代码 2026-06-26）
- 数据库：`postgres` 容器（`172.20.0.29:5432`，容器名 `postgres`，未暴露端口到宿主机）
- 生产镜像 `amz-listing-management-system:2026-06-15` 不含 V2 代码，故不能在容器内运行此 CLI

完整 JSON 输出附件：`/tmp/chair-v2-output.json`（318 条 condition_traces，本文仅引用关键片段）。

## 2. Phase 1 Acceptance 逐项验证

### 2.1 Acceptance 1 — V2 能打印 CHAIR `meow2511081Gqqd` 的 applicable required tree

**通过。** 输出顶层结构：

```text
sku: meow2511081Gqqd
product_type: CHAIR
candidate_attribute_names: [...]
requirement_tree:
  path_key_version: v2_path_keys_2026_06
  iteration_count: 1
  non_converged: false
  required_paths: 72 条（含子路径）
  non_applicable_required_paths: 77 条
  unknown_required_paths: 0 条
  condition_traces: 318 条
  root: RequirementNode (递归树)
```

### 2.2 Acceptance 2 — 不静态爆炸 CHAIR 的 conditional offer/hazmat/battery required

**通过。** 电池/危险品/合规类条件 required 全部落在 `non_applicable_required_paths`：

```text
battery, battery_contains_free_unabsorbed_liquid, battery_installation_device_type,
contains_battery_or_cell, ghs, has_multiple_battery_powered_components, hazmat,
is_battery_non_spillable, lithium_battery, non_lithium_battery_packaging,
number_of_lithium_ion_cells, number_of_lithium_metal_cells, safety_data_sheet_url,
baa_taa_compliance_acknowledgement, taa_compliant_country,
batteries_included, batteries_required, has_less_than_30_percent_state_of_charge
```

变体相关条件 required 也全部 non-applicable：

```text
child_parent_sku_relationship, package_contains_sku, variation_theme
```

`required_paths` 中未出现任何电池/危险品/变体相关 path。

### 2.3 Acceptance 3 — 能解释 condition 匹配与非匹配

**通过。** `frame_material` 的 condition trace 清晰可读：

```json
{
  "schema_path": "$.allOf[62]",
  "operator": "if",
  "result": "false",
  "reason": "condition evaluated against candidate payload",
  "dependent_paths": ["child_parent_sku_relationship"],
  "introduced_required_paths": [],
  "non_applicable_required_paths": ["frame_material"],
  "unknown_required_paths": []
}
```

解读：`$.allOf[62].if` 依赖 `child_parent_sku_relationship`。当前 payload 无此字段（非变体关系），`if` 求值为 `false`，`then` 分支不适用，`frame_material`（在 `then.required` 内）被标为 `non_applicable`。这正是 Epic 第 1 节"Background"要求的行为：不静态合并所有 `then.required`。

### 2.4 Acceptance 4 — ADR 定义条件求值迭代顺序、收敛限制、unknown-condition fail-closed 范围

**通过（文档侧）。** ADR 第 63–82 行定义：
- 迭代算法：seed → resolve → render candidate → re-evaluate → 直到 required path set 稳定或达到 `MAX_ITERATIONS`
- 收敛限制：首版 `MAX_ITERATIONS = 3`（模块设计 §5）
- Unknown-condition fail-closed 范围：仅阻断受影响分支，不爆炸为 product-type-wide required

实证：`iteration_count = 1`，`non_converged = false`，`unknown_required_paths = []`。CHAIR 单 SKU 一轮即收敛，远低于上限。

### 2.5 Acceptance 5 — 模块设计定义 stable path key 规则

**通过（文档侧）。** 模块设计 §3 定义：
- 对象子项用 dot path：`frame.color`
- measure 用语义子键：`maximum_weight_recommendation.value` / `.unit`
- array_object 用 selector：`frame{marketplace_id=ATVPDKIKX0DER}.color`
- selector 缺失时用 deterministic fingerprint
- `path_key_version = "v2_path_keys_2026_06"`

实证输出 `path_key_version` 与契约一致；`item_depth_width_height`（`array_object`，`selectors=["marketplace_id"]`）、`frame.color`、`maximum_weight_recommendation.value` 等 path key 均符合规则。

## 3. V1 vs V2 对比（重大发现）

V1 `AmazonSchemaService.get_expanded_required_properties("CHAIR")` 只返回 **6 个** top-level required：

```text
brand, bullet_point, country_of_origin, item_name,
product_description, supplier_declared_dg_hz_regulation
```

V2 `required_paths` 包含 **28 个** top-level required（含子路径共 72 条）：

```text
brand, bullet_point, color, condition_type, country_of_origin,
externally_assigned_product_identifier, frame, fulfillment_availability,
included_components, is_assembly_required, is_fragile,
item_depth_width_height, item_name, item_shape, item_weight,
list_price, manufacturer, material, maximum_weight_recommendation,
merchant_shipping_group, merchant_suggested_asin, model_name,
model_number, number_of_items, part_number, product_description,
seat, supplier_declared_dg_hz_regulation
```

**结论**：V1 严重漏检 22 个 top-level required，其中包括 Epic 明确点名的 `frame`、`seat`、`item_depth_width_height`。V2 不仅未引入回归，还修复了 V1 的核心漏检问题。这与 Epic 第 1 节"Background"中描述的"`AmazonSchemaService.get_expanded_required_properties("CHAIR")` returns only the top-level required list"完全吻合。

## 4. Schema 形状识别证据

RequirementTree 正确识别了 Epic 关注的对象/measure/array_object 形状：

- `item_depth_width_height`：`shape=array_object`，`selectors=["marketplace_id"]`，`required_children=["depth","height","width"]`
  - `item_depth_width_height.depth`：`shape=measure`，`unit_values=["inches"]`，`required_children=["unit","value"]`
- `frame`：`shape=object`，`required_children=["color"]`
  - `frame.color`：`shape=list_value`，`required_children=["value"]`
- `condition_type`：`shape=array_object`，`auto_fields={"marketplace_id":"ATVPDKIKX0DER"}`，enum 13 个值
- `list_price`：`shape=array_object`，`selectors=["marketplace_id","currency"]`，`required_children=["currency","value"]`

## 5. 潜在 Follow-up（不阻塞 S5）

### 5.1 同一 path_key 同时出现在 required 和 non_applicable

7 个 top-level path 同时出现在两列表中：

```text
color, frame, item_shape, material, model_number, number_of_items, seat
```

原因分析：Amazon schema 在多个 `allOf` 分支中对同一属性名既有 unconditional required 定义，又有 conditional required 定义。V2 目前两者都列出，未做去重或合并。

影响评估：Phase 1 read-only 阶段可接受（condition_traces 能解释来源）。但进入 S4 evidence resolver / S9 coverage gate 时需明确：同一 path_key 的 required 语义优先于 non_applicable 语义，否则 coverage gate 可能误判。建议在 S4 启动前确认处理策略。

### 5.2 `color` 在 required_paths 缺 `.value` 子项

`brand` 有 `brand` + `brand.value`，但 `color` 只有父节点 `color`，无 `color.value`。可能 schema 形状差异（直接 scalar vs list_value）。需确认 `payload_composer_v2.py` 能否正确处理这种形状，避免 S8 渲染时遗漏。

### 5.3 condition_traces 数量较大（318 条）

大部分 trace 的 `introduced_required_paths`、`non_applicable_required_paths`、`unknown_required_paths` 均为空。进入 S7 review adapter 时建议过滤，只暴露有内容的 trace 给 review UI，避免噪声。

### 5.4 V2 代码未进生产镜像

生产镜像 `amz-listing-management-system:2026-06-15` 不含 V2 代码。本次实证需用宿主机源码 + 容器 DB IP 运行。进入 S4 之前不阻塞，但 S10（strict preview integration）和 S12（shadow mode）之前必须构建含 V2 的新镜像。

## 6. 结论

**Phase 1 Acceptance 全部通过。**

- 5 条 acceptance 逐项满足，证据可追溯
- V2 修复了 V1 的 22 个 top-level required 漏检（核心问题）
- 不爆炸 conditional required（电池/危险品/变体全部 non-applicable）
- 一轮收敛，无 unknown required
- condition_traces 可读、可解释

**建议下一步**：
1. 进入 S4 之前先决策 Open Question 1（V2 review 持久化形式）
2. S4 实现时关注 §5.1 的 path_key 重复问题
3. S5 启动前构建含 V2 代码的开发镜像，避免长期依赖宿主机直跑

## 7. 复现方式

```bash
# 1. 取容器 DB 凭证
DB_PASS=$(docker exec amz-listing-management-system printenv DATABASE_PASSWORD)

# 2. 宿主机运行（需 cd ~/amz_listing_management_system）
DATABASE_HOST=172.20.0.29 DATABASE_PORT=5432 DATABASE_NAME=amz_listing \
DATABASE_USER=amz_listing DATABASE_PASSWORD="$DB_PASS" \
  python3 main.py --task analyze-listing-requirements-v2 \
    --category CHAIR --sku meow2511081Gqqd > /tmp/chair-v2-output.json
```
