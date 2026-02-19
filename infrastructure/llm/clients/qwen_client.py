"""千问API客户端（简化版）"""
import logging
import json
from typing import Dict, Any
from http import HTTPStatus
import dashscope
from dashscope.api_entities.dashscope_response import GenerationResponse
from src.config.settings import settings

logger = logging.getLogger(__name__)

class QwenAPIClient:
    """千问API客户端"""
    
    def __init__(self):
        self.api_key = settings.DASHSCOPE_API_KEY
        if not self.api_key:
            raise EnvironmentError("请设置DASHSCOPE_API_KEY配置")
        
        dashscope.api_key = self.api_key
        logger.info("千问客户端初始化完成")
    
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        json_mode: bool = False,
        temperature: float = 0.7
    ) -> Dict[str, Any]:
        """生成内容"""
        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt}
        ]
        
        try:
            response: GenerationResponse = dashscope.Generation.call(
                model=model,
                messages=messages,
                result_format='message',
                temperature=temperature,
            )
            
            if response.status_code == HTTPStatus.OK:
                content = response.output.choices[0]['message']['content']
                usage = response.usage if hasattr(response, 'usage') else {}
                
                if json_mode:
                    return {
                        "content": json.loads(content),
                        "usage": usage
                    }
                else:
                    return {
                        "content": content,
                        "usage": usage
                    }
            else:
                raise ValueError(f"API错误: {response.code} - {response.message}")
                
        except json.JSONDecodeError as e:
            # content variable might not be defined if error happens before assignment
            # but standard logic suggests it happens in json.loads
            logger.error(f"JSON解析失败")
            raise ValueError(f"无效JSON响应: {e}")
        except Exception as e:
            logger.error(f"千问API错误: {e}")
            raise
