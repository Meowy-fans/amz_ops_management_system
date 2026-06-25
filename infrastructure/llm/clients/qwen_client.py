"""千问API客户端（简化版）"""
import logging
import json
from typing import Dict, Any
from http import HTTPStatus
import dashscope
from dashscope.api_entities.dashscope_response import GenerationResponse
from src.config.settings import settings

logger = logging.getLogger(__name__)
_JSON_ERROR_PREVIEW_LIMIT = 1000


def _json_error_preview(content: Any) -> str:
    text = str(content or "")
    if len(text) <= _JSON_ERROR_PREVIEW_LIMIT:
        return text
    return f"{text[:_JSON_ERROR_PREVIEW_LIMIT]}...[truncated]"


def _contains_json_instruction(messages: list[Dict[str, str]]) -> bool:
    return any("json" in str(message.get("content") or "").lower() for message in messages)


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
        if json_mode and not _contains_json_instruction(messages):
            messages.insert(
                0,
                {
                    "role": "system",
                    "content": "Return valid JSON only. The output must be a JSON object.",
                },
            )
        content = ""
        request_kwargs = {
            "model": model,
            "messages": messages,
            "result_format": "message",
            "temperature": temperature,
        }
        if json_mode:
            request_kwargs["response_format"] = {"type": "json_object"}
        
        try:
            response: GenerationResponse = dashscope.Generation.call(**request_kwargs)
            
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
            logger.error(
                "JSON解析失败 | provider=qwen model=%s content_len=%s content_preview=%r",
                model,
                len(str(content or "")),
                _json_error_preview(content),
            )
            raise ValueError(f"无效JSON响应: {e}")
        except Exception as e:
            logger.error(f"千问API错误: {e}")
            raise
