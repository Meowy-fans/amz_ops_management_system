"""品类服务"""
from sqlalchemy.orm import Session
from src.repositories.category_repository import CategoryRepository
from src.services.progress_reporter import ProgressReporter
import logging
from typing import List, Tuple, Dict
from collections import defaultdict

logger = logging.getLogger(__name__)

class CategoryService:
    """品类服务 - 负责SKU品类判定"""
    
    def __init__(self, db: Session, reporter: ProgressReporter | None = None):
        self.db = db
        self.repo = CategoryRepository(db=self.db)
        self.reporter = reporter or ProgressReporter()
    
    def categorize_skus(self, sku_list: List[str]) -> Tuple[Dict[str, List[str]], List[str]]:
        """
        为SKU列表分配品类
        
        Args:
            sku_list: 待分类的meow_sku列表
            
        Returns:
            (categorized_skus, uncategorized_skus)
            - categorized_skus: {category_name: [sku1, sku2, ...]}
            - uncategorized_skus: [sku1, sku2, ...]
        """
        if not sku_list:
            return {}, []
        
        logger.info(f"开始为 {len(sku_list)} 个SKU进行品类判断...")
        self.reporter.emit(f"   🔍 品类匹配中...")
        
        # 调用Repository获取映射关系
        mappings = self.repo.get_sku_to_category_mapping(sku_list)
        
        categorized_skus = defaultdict(list)
        uncategorized_skus = []
        processed_skus = set()
        
        for meow_sku, category_name in mappings:
            processed_skus.add(meow_sku)
            if category_name:
                categorized_skus[category_name].append(meow_sku)
            else:
                uncategorized_skus.append(meow_sku)
        
        # 找出未返回的SKU
        for sku in sku_list:
            if sku not in processed_skus:
                uncategorized_skus.append(sku)
        
        logger.info(f"品类判断完成。已分类: {sum(len(v) for v in categorized_skus.values())}, 未分类: {len(uncategorized_skus)}")
        
        if uncategorized_skus:
            logger.warning(f"{len(uncategorized_skus)} 个SKU未找到品类映射")
            self.reporter.emit(f"   ⚠️  {len(uncategorized_skus)} 个SKU未找到品类（将使用默认配置）")
        
        return dict(categorized_skus), uncategorized_skus
