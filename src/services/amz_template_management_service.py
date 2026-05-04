"""
Amazon Template Management Service
亚马逊类目模板管理服务

负责编排更新亚马逊类目模板的整个业务流程，包括基于报错的规则矫正
"""
from src.services.amz_template_parser import AdvancedTemplateParser
from src.services.amz_template_rule_correction import (
    apply_required_field_corrections,
    parse_report_for_required_fields,
)
from src.services.template_variation_config import (
    DEFAULT_PRIORITY_THEMES,
    determine_priority_themes,
    generate_variation_mapping,
)
from src.repositories.amz_template_repository import AmzTemplateRepository
from src.services.progress_reporter import ProgressReporter
from sqlalchemy.orm import Session
import os
import logging
from typing import Tuple, Dict, List, Set

logger = logging.getLogger(__name__)

class TemplateManagementService:
    """
    服务层
    
    负责编排更新亚马逊类目模板的整个业务流程，包括基于报错的规则矫正
    """

    def __init__(self, db: Session, reporter: ProgressReporter | None = None):
        """
        初始化服务
        
        Args:
            db: SQLAlchemy Session 对象
        """
        self.db = db
        self.repo = AmzTemplateRepository(db=self.db)
        self.reporter = reporter or ProgressReporter()

    def update_template_from_file(
        self, 
        file_path: str, 
        category: str
    ) -> Tuple[bool, str]:
        """
        处理单个模板文件的核心业务逻辑
        
        流程：
        1. 解析 Excel 模板文件
        2. 生成变体属性映射
        3. 确定优先级主题
        4. 保存到数据库
        
        Args:
            file_path: Excel 模板文件的完整路径
            category: 品类名称（如 'HOME_MIRROR', 'CABINET'）
            
        Returns:
            元组 (操作是否成功, 相关消息)
        """
        logger.info(
            f"🚀 开始处理模板文件 '{file_path}'，品类为 '{category}'..."
        )

        # 验证文件存在
        if not file_path or not os.path.exists(file_path):
            message = f"文件不存在或路径无效: {file_path}"
            logger.error(message)
            return False, message

        # 步骤1：解析模板文件
        logger.info("调用解析器模块...")
        parser = AdvancedTemplateParser(file_path)
        parse_success, parse_message = parser.parse()

        if not parse_success:
            logger.error(f"模板解析失败: {parse_message}")
            return False, f"模板解析失败: {parse_message}"

        results = parser.get_results()

        # 步骤2：生成变体属性映射
        logger.info("开始自动生成变体属性映射...")
        template_fields = results.get("fields", [])
        variation_themes = parser.get_all_variation_themes()
        variation_mapping = self._generate_variation_mapping(
            template_fields, 
            variation_themes
        )
        results["variation_mapping"] = variation_mapping

        # 步骤3：确定优先级主题
        priority_themes = self._determine_priority_themes(category)
        results["priority_themes"] = priority_themes

        # 步骤4：保存到数据库
        logger.info("调用仓库层以保存数据...")
        template_name = os.path.basename(file_path)

        inserted_id = self.repo.save_parsed_data(
            category=category,
            template_name=template_name,
            results=results
        )

        if inserted_id is not None:
            message = (
                f"模板 '{template_name}' 已成功处理并存入数据库 "
                f"(ID: {inserted_id})。"
            )
            logger.info(message)
            self.reporter.emit(
                f"\n✅ 成功! 最终为品类 '{category}' "
                f"保存的高优先级主题为: {priority_themes}"
            )
            return True, message
        else:
            message = "数据保存到数据库失败，请检查日志获取详细信息。"
            logger.error(message)
            return False, message

    def correct_rules_from_report(
        self, 
        report_path: str, 
        category: str
    ) -> Tuple[bool, str]:
        """
        从亚马逊报错文件中自动矫正模板的必填字段规则
        
        流程：
        1. 解析报错文件，提取需要修正的字段名
        2. 从数据库获取当前的字段定义
        3. 矫正字段定义并写回数据库
        
        Args:
            report_path: 亚马逊报错文件 (.xlsm) 的完整路径
            category: 该文件对应的品类名称
            
        Returns:
            元组 (操作是否成功, 相关消息)
        """
        self.reporter.emit(f"\n🚀 启动模板规则自动矫正流程，品类: '{category}'...")

        # 步骤 1: 解析报错文件，提取需要修正的字段名
        try:
            self.reporter.emit(
                f"➡️ 步骤 1/3: 正在解析报错文件 "
                f"'{os.path.basename(report_path)}'..."
            )
            required_fields = self._parse_report_for_required_fields(report_path)
            
            if not required_fields:
                message = (
                    "✅ 解析完成，但未在报错文件中找到与'必填项缺失'"
                    "相关的错误 (Error code 90220)。无需矫正。"
                )
                self.reporter.emit(message)
                return True, message
                
            self.reporter.emit(f"✔️ 从报告中识别出 {len(required_fields)} 个必填字段。")

        except Exception as e:
            message = f"❌ 解析报错文件时失败: {e}"
            logger.exception(message)
            self.reporter.emit(message)
            return False, message

        # 步骤 2: 从数据库获取当前的字段定义
        self.reporter.emit("➡️ 步骤 2/3: 正在从数据库获取当前模板规则...")
        db_result = self.repo.find_latest_template_id_and_defs(category)
        
        if not db_result:
            message = (
                f"❌ 未能在数据库中找到品类 '{category}' 的模板记录，"
                "无法执行矫正。"
            )
            self.reporter.emit(message)
            return False, message

        record_id, field_definitions = db_result
        self.reporter.emit("✔️ 成功获取数据库记录。")

        # 步骤 3: 矫正字段定义并写回数据库
        try:
            self.reporter.emit("➡️ 步骤 3/3: 正在矫正规则并更新数据库...")
            updated_defs, corrected_fields = self._apply_corrections(
                field_definitions, 
                required_fields
            )

            if not corrected_fields:
                message = (
                    "✅ 所有在报错文件中提及的必填字段，"
                    "在数据库中已是必填状态。无需矫正。"
                )
                self.reporter.emit(message)
                return True, message

            success = self.repo.update_field_definitions_by_id(
                record_id, 
                updated_defs
            )
            
            if success:
                self.db.commit()
                final_message = (
                    f"✅ 成功！已为品类 '{category}' 矫正了 "
                    f"{len(corrected_fields)} 个字段的必填规则:\n   - "
                    + "\n   - ".join(sorted(list(corrected_fields)))
                )
                self.reporter.emit(final_message)
                return True, final_message
            else:
                self.db.rollback()
                message = "❌ 更新数据库时发生错误，操作已回滚。"
                self.reporter.emit(message)
                return False, message
                
        except Exception as e:
            self.db.rollback()
            message = f"❌ 在矫正和更新过程中发生未知错误: {e}"
            logger.exception(message)
            self.reporter.emit(message)
            return False, message

    def _generate_variation_mapping(
        self, 
        template_fields: List[str], 
        variation_themes: List[str]
    ) -> Dict[str, str]:
        """
        生成变体属性映射
        
        将内部属性名（如 color_name）映射到模板中的实际字段名
        
        Args:
            template_fields: 模板中的所有字段列表
            variation_themes: 变体主题列表
            
        Returns:
            变体映射字典，例如 {'color_name': 'Color', 'size_name': 'Size'}
        """
        return generate_variation_mapping(template_fields, variation_themes)

    def _determine_priority_themes(self, category: str) -> List[str]:
        """
        确定优先级主题
        
        优先级：用户输入 > 历史配置 > 系统默认
        
        Args:
            category: 品类名称
            
        Returns:
            高优先级主题列表
        """
        return determine_priority_themes(category, self.repo, self.reporter)

    def _parse_report_for_required_fields(self, file_path: str) -> Set[str]:
        """
        解析亚马逊报错 .xlsm 文件，提取因 'is required but not supplied' 
        导致的错误字段名
        
        Args:
            file_path: 报错文件路径
            
        Returns:
            必填字段名的集合
        """
        return parse_report_for_required_fields(file_path)

    def _apply_corrections(
        self, 
        definitions: Dict, 
        fields_to_correct: Set[str]
    ) -> Tuple[Dict, Set[str]]:
        """
        将从报错文件中解析出的字段名应用到从数据库获取的字段定义中
        
        Args:
            definitions: 字段定义字典
            fields_to_correct: 需要矫正的字段名集合
            
        Returns:
            元组 (更新后的定义字典, 实际矫正的字段集合)
        """
        return apply_required_field_corrections(definitions, fields_to_correct)
