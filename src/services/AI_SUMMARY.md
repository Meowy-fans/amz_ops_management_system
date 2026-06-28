# services — AI 模块上下文

**目的**: 管理 Amazon 发品属性解析、审核、需求树分析与 payload 生成流程。

**输入**: Amazon listing draft、Product Type schema、candidate payload、attribute rules、review policy、pending review repository。

**输出**: attribute resolutions、RequirementTree、ResolutionTree、V2 attributes payload、tree-level coverage decisions、review decisions、shadow audit rows、shadow diff reports、regression go/no-go reports、rule skeleton YAML、submission results。

**不变量**: 未审核的 required LLM 属性不得进入 Amazon submitter。

**关键边界**: 不直接跨模块查询其他业务表，不在 service 启动时执行 DDL；V2 shadow mode 只写审计，不改变 V1 发品决策。

**最后更新**: 2026-06-27 by Codex
