# Amazon Listing Management System

亚马逊发品管理系统 - 自动化生成Amazon发品Excel文件

---

## 🚀 快速开始

> **项目状态**：[查看进度 (STATUS.md)](./STATUS.md) | [待办任务 (TODO.md)](./TODO.md)

### 1. 查看帮助
```bash
python main.py --help
```

### 2. 列出所有可用品类
```bash
python main.py --list
```

### 3. 生成发品文件
```bash
# 生成 CABINET 品类的发品文件
python main.py -c CABINET

# 生成 HOME_MIRROR 品类的发品文件
python main.py -c HOME_MIRROR
```

### 4. 使用调试日志
```bash
python main.py -c CABINET --log DEBUG
```

---

## 📋 系统架构

```
项目结构
├── main.py                     # 主程序入口
├── infrastructure/             # 基础设施层
│   └── db_pool.py             # 数据库连接池
├── src/
│   ├── repositories/          # 数据仓库层
│   │   ├── product_listing_repository.py
│   │   ├── product_data_repository.py
│   │   ├── amz_template_repository.py
│   │   └── amz_listing_log_repository.py
│   ├── services/              # 服务层
│   │   └── product_listing_service.py
│   └── utils/                 # 工具层
│       ├── data_mapping_helper.py
│       ├── excel_generator.py
│       └── variation_helper.py
├── config/                    # 配置文件
│   └── amz_listing_data_mapping/
│       ├── amz_mapping.json
│       └── category_mapping.json
├── template_files/            # Excel模板文件
│   ├── CABINET.xlsm
│   └── HOME_MIRROR.xlsm
└── output/                    # 输出文件目录
```

---

## 🔄 发品流程

1. **获取待发品SKU** - 从数据库筛选符合条件的SKU
2. **SKU品类映射** - 将SKU映射到标准品类
3. **变体识别** - 使用图论DFS算法识别变体家族
4. **加载模板规则** - 加载对应品类的字段定义和验证规则
5. **数据映射** - 将产品数据映射到Amazon字段
6. **Excel生成** - 填充模板并生成.xlsm文件
7. **日志记录** - 记录发品批次和状态

---

## 📦 依赖要求

```toml
[project]
dependencies = [
    "sqlalchemy>=2.0.23",
    "psycopg2-binary>=2.9.9",
    "pandas>=2.1.3",
    "python-dotenv>=1.0.0",
    "openpyxl>=3.1.2",
]
```

---

## 🧪 运行测试

### 单元测试
```bash
# Repository层测试
python tests/test_product_listing_repository.py
python tests/test_product_data_repository.py
python tests/test_amz_template_repository.py
python tests/test_amz_listing_log_repository.py

# 工具层测试
python tests/test_data_mapping_helper.py
python tests/test_excel_generator.py
python tests/test_variation_helper.py

# 服务层测试
python tests/test_product_listing_service.py
```

### 集成测试
```bash
python tests/test_e2e_integration.py
```

---

## 📊 输出示例

```
============================================================
🚀 Amazon Listing Management System
📦 品类: CABINET
⏰ 时间: 2025-11-15 16:30:00
============================================================

步骤1: 获取所有待发品SKU...
  找到 358 个待发品SKU
步骤2: 获取SKU品类映射...
  成功映射 358 个SKU
步骤3: 过滤品类 'CABINET'...
  品类 'CABINET' 有 240 个待发品SKU
步骤4: 获取变体关联数据...
步骤5: 识别变体家族...
  单品: 20 个
  变体家族: 42 个
步骤6: 加载品类模板...
步骤7: 处理单品...
  成功处理 20/20 个单品
步骤8: 处理变体家族...
  成功处理 42 个变体家族，生成 262 行
步骤9: 合并所有行
  总共生成 282 行数据
步骤10: 生成Excel文件...
  成功生成Excel文件: output/AmazonUpload_CABINET_20251115_163000_batch_6d024399.xlsm
步骤11: 记录发品日志...
  保存了 282 条日志

============================================================
✅ 发品文件生成成功！
============================================================
📊 统计信息:
   - 单品数量: 20
   - 变体家族: 42
   - 总行数: 282
   - 批次ID: 6d024399-d0d9-4db6-9c28-afa414414bec

📁 输出文件:
   output/AmazonUpload_CABINET_20251115_163000_batch_6d024399.xlsm
============================================================
```

---

## 🔧 故障排查

### 问题：找不到模板文件
**解决**：确保 `template_files/` 目录下有对应品类的 .xlsm 模板文件

### 问题：没有待发品SKU
**解决**：检查数据库中是否有符合条件的SKU（未在Amazon报告中、非超大件、可用价格等）

### 问题：数据库连接失败
**解决**：检查 `.env` 文件中的数据库配置是否正确

---

## 📝 开发日志

- ✅ Repository层（4个模块）
- ✅ 工具层（3个模块）
- ✅ 服务层（1个模块）
- ✅ 主程序入口
- ✅ 集成测试

---

## 📄 许可

内部项目 - 保留所有权利