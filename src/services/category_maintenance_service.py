# src/services/category_maintenance_service.py
"""
Category Maintenance Service
品类维护服务

负责维护 supplier_categories_map 表，同步 Giga 供应商的品类映射
"""

from sqlalchemy.orm import Session
from src.repositories.category_repository import CategoryRepository
from src.services.category_mapping_csv_updater import CategoryMappingCsvUpdater
from src.services.progress_reporter import ProgressReporter
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)


class CategoryMaintenanceService:
    """
    品类维护服务
    负责维护 supplier_categories_map 表
    """
    
    def __init__(self, db: Session, reporter: ProgressReporter | None = None):
        self.db = db
        self.repository = CategoryRepository(db)
        self.reporter = reporter or ProgressReporter()
    
    def sync_giga_categories(self) -> Dict:
        """
        同步 Giga 品类到映射表
        
        流程:
        1. 获取 Giga 所有品类代码（从 giga_product_sync_records）
        2. 获取已存在的映射（从 supplier_categories_map）
        3. 找出新品类（对比差异）
        4. 插入新映射（supplier_platform 硬编码为 'giga'）
        
        注意：
        - supplier_platform 硬编码为 'giga'，因为数据源是 giga_product_sync_records 表
        - standard_category_name 留空（空字符串），待后续手动维护
        - supplier_category_name 从 raw_data->>'category' 提取
        
        Returns:
            {
                'total_giga_categories': 50,      # Giga 中的品类总数
                'existing_mappings': 35,          # 已存在的映射
                'new_categories': 15,             # 新发现的品类
                'inserted_count': 15,             # 成功插入的数量
                'new_category_list': [...]        # 新增的品类列表
            }
        """
        logger.info("🚀 开始同步 Giga 品类映射...")
        self.reporter.emit("\n" + "=" * 70)
        self.reporter.emit("🔄 同步 Giga 品类映射")
        self.reporter.emit("=" * 70)
        
        # 1. 获取 Giga 中的所有品类
        self.reporter.emit("\n➡️ 步骤 1/4: 查询 Giga 同步记录中的品类...")
        giga_categories = self.repository.get_giga_category_codes()
        self.reporter.emit(f"✅ 发现 {len(giga_categories)} 个不同的品类代码")
        
        if not giga_categories:
            self.reporter.emit("\n⚠️  未找到任何品类代码，流程结束")
            logger.warning("No category codes found in giga_product_sync_records")
            return {
                'total_giga_categories': 0,
                'existing_mappings': 0,
                'new_categories': 0,
                'inserted_count': 0,
                'new_category_list': []
            }
        
        # 2. 获取已存在的映射（只查询 giga 平台）
        self.reporter.emit("\n➡️ 步骤 2/4: 查询已存在的品类映射...")
        existing_codes = self.repository.get_existing_category_codes('giga')
        self.reporter.emit(f"✅ 已有 {len(existing_codes)} 个品类映射")
        
        # 3. 找出新品类
        self.reporter.emit("\n➡️ 步骤 3/4: 对比差异，找出新品类...")
        new_categories = [
            cat for cat in giga_categories 
            if cat['category_code'] not in existing_codes
        ]
        
        if not new_categories:
            self.reporter.emit("\n✅ 没有发现新品类，所有品类都已映射")
            logger.info("No new categories to sync")
            
            # 显示未映射品类的统计（即使没有新增）
            self._display_unmapped_categories_statistics()
            
            return {
                'total_giga_categories': len(giga_categories),
                'existing_mappings': len(existing_codes),
                'new_categories': 0,
                'inserted_count': 0,
                'new_category_list': []
            }
        
        self.reporter.emit(f"\n🆕 发现 {len(new_categories)} 个新品类需要添加:")
        # 显示前10个新品类
        display_limit = min(10, len(new_categories))
        for i, cat in enumerate(new_categories[:display_limit], 1):
            self.reporter.emit(f"   {i:2d}. {cat['category_code']:<15} - {cat['category_name']}")
        if len(new_categories) > display_limit:
            self.reporter.emit(f"   ... 还有 {len(new_categories) - display_limit} 个")
        
        # 4. 准备插入数据
        self.reporter.emit("\n➡️ 步骤 4/4: 插入新品类映射...")
        
        # 注意：supplier_platform 硬编码为 'giga'
        # 因为数据来源是 giga_product_sync_records 表
        mappings = [
            {
                'supplier_platform': 'giga',  # 硬编码，数据来源决定
                'supplier_category_code': cat['category_code'],
                'supplier_category_name': cat['category_name'],
                'standard_category_name': ''  # 留空，待手动维护
            }
            for cat in new_categories
        ]
        
        # 5. 批量插入
        try:
            inserted_count = self.repository.batch_insert_category_mappings(mappings)
            
            self.reporter.emit(f"✅ 成功插入 {inserted_count} 条新品类映射")
            
            # 显示统计结果
            self.reporter.emit("\n" + "=" * 70)
            self.reporter.emit("📊 同步完成统计")
            self.reporter.emit("=" * 70)
            self.reporter.emit(f"Giga 品类总数:      {len(giga_categories)}")
            self.reporter.emit(f"已存在的映射:       {len(existing_codes)}")
            self.reporter.emit(f"新发现的品类:       {len(new_categories)}")
            self.reporter.emit(f"成功插入记录:       {inserted_count}")
            self.reporter.emit("=" * 70)
            
            # 提示需要维护 standard_category_name
            if inserted_count > 0:
                self.reporter.emit("\n⚠️  重要提示:")
                self.reporter.emit("   新增的品类映射中 standard_category_name 为空")
                self.reporter.emit("   请在数据库中手动维护标准品类名称")
                self.reporter.emit()
                self.reporter.emit("   示例 SQL:")
                self.reporter.emit("   UPDATE supplier_categories_map")
                self.reporter.emit("   SET standard_category_name = 'your_standard_name'")
                self.reporter.emit("   WHERE supplier_platform = 'giga'")
                self.reporter.emit("     AND supplier_category_code = 'YOUR_CODE'")
                self.reporter.emit("     AND standard_category_name = '';")
                self.reporter.emit()
            
            logger.info(f"Category sync completed: inserted {inserted_count} new mappings")
            
            # 显示未映射品类的统计
            self._display_unmapped_categories_statistics()
            
            return {
                'total_giga_categories': len(giga_categories),
                'existing_mappings': len(existing_codes),
                'new_categories': len(new_categories),
                'inserted_count': inserted_count,
                'new_category_list': new_categories
            }
            
        except Exception as e:
            self.reporter.emit(f"\n❌ 插入失败: {e}")
            logger.error(f"Failed to insert category mappings: {e}", exc_info=True)
            raise
    
    def _display_unmapped_categories_statistics(self):
        """显示未完成映射的品类统计信息"""
        self.reporter.emit("\n" + "=" * 70)
        self.reporter.emit("📊 待维护品类统计（按商品数量排序）")
        self.reporter.emit("=" * 70)
        
        unmapped_stats = self.repository.get_unmapped_categories_with_product_count('giga')
        
        if not unmapped_stats:
            self.reporter.emit("✅ 所有品类都已完成映射")
            self.reporter.emit("=" * 70)
            return
        
        total_unmapped_products = sum(item['product_count'] for item in unmapped_stats)
        
        self.reporter.emit(f"\n待维护品类数量: {len(unmapped_stats)}")
        self.reporter.emit(f"涉及商品总数: {total_unmapped_products}")
        self.reporter.emit()
        self.reporter.emit(f"{'序号':<6} {'品类代码':<20} {'品类名称':<30} {'商品数量':>10}")
        self.reporter.emit("-" * 70)
        
        for i, item in enumerate(unmapped_stats, 1):
            code = item['category_code'][:18] if len(item['category_code']) > 18 else item['category_code']
            name = item['category_name'][:28] if len(item['category_name']) > 28 else item['category_name']
            count = item['product_count']
            
            self.reporter.emit(f"{i:<6} {code:<20} {name:<30} {count:>10,}")
        
        self.reporter.emit("=" * 70)
        self.reporter.emit("\n💡 提示: 请在数据库中为这些品类维护 standard_category_name")
        self.reporter.emit("   示例 SQL:")
        self.reporter.emit("   UPDATE supplier_categories_map")
        self.reporter.emit("   SET standard_category_name = '标准品类名'")
        self.reporter.emit("   WHERE supplier_platform = 'giga'")
        self.reporter.emit("     AND supplier_category_code = '品类代码';")
        self.reporter.emit()
    
    def update_mappings_from_csv(self, csv_file_path: str) -> Dict:
        """
        从 CSV 文件批量更新品类映射
        
        Args:
            csv_file_path: CSV 文件路径
            
        Returns:
            {
                'total_rows': 100,           # CSV 总行数
                'valid_rows': 95,            # 验证通过的行数
                'invalid_rows': 5,           # 验证失败的行数
                'updated_count': 90,         # 成功更新的数量
                'errors': [...]              # 错误详情
            }
        """
        updater = CategoryMappingCsvUpdater(self.repository, self.reporter)
        return updater.update_mappings_from_csv(csv_file_path)
