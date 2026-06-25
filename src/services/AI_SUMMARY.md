# services — AI 模块上下文

**目的**: 管理 Amazon 发品属性解析审核提交流程。

**输入**: Amazon listing draft、schema service、review policy、pending review repository。

**输出**: attribute resolutions、coverage decisions、review decisions、submission results。

**不变量**: 未审核的 required LLM 属性不得进入 Amazon submitter。

**关键边界**: 不直接跨模块查询其他业务表，不在 service 启动时执行 DDL。

**最后更新**: 2026-06-25 by Cursor
