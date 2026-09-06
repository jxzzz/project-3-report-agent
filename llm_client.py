import json
import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("DEEPSEEK_API_KEY")
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
URL = "https://api.deepseek.com/chat/completions"


class LLMError(RuntimeError):
    pass


def _require_api_key() -> None:
    if not API_KEY:
        raise LLMError("缺少 DEEPSEEK_API_KEY，请检查 .env")


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = text.removeprefix("```json").removesuffix("```")
    elif text.startswith("```"):
        text = text.removeprefix("```").removesuffix("```")
    return text.strip()


def parse_json(text: str) -> dict:
    cleaned = _strip_json_fence(text)
    return json.loads(cleaned)


def chat(messages: list, temperature: float = 0.2, json_mode: bool = False) -> dict:
    _require_api_key()

    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
    }

    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    
    response = requests.post(
        URL,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json= payload,
        timeout=60,
    )

    if response.status_code != 200:
        raise LLMError(f"API 请求失败：{response.status_code} {response.text}")

    data = response.json()
    content = data["choices"][0]["message"]["content"] or ""

    return {
        "content": content,
        "usage": data.get("usage", {}),
    }


def chat_json(
    system_prompt: str,
    user_content: str,
    temperature: float = 0.2,
    max_retries: int = 3,
) -> dict:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    usage_records = []
    last_raw = ""
    last_error = ""

    for attempt in range(1, max_retries + 1):
        if attempt > 1:
            repair_messages = messages + [
                {"role": "assistant", "content": last_raw},
                {
                    "role": "user",
                    "content": (
                        "你上一次输出不是合法 JSON："
                        f"{last_error}\n"
                        "请重新输出一个完整的 JSON 对象，不要省略，不要使用截断内容。"
                    ),
                },
            ]

            result = chat(
                repair_messages,
                temperature=0.0,
                json_mode=True,
            )
        else:
            result = chat(
                messages,
                temperature=temperature,
                json_mode=True,
            )

        usage_records.append(result["usage"])
        last_raw = result["content"]

        try:
            parsed = parse_json(last_raw)

            if not isinstance(parsed, dict):
                raise ValueError("模型输出不是 JSON 对象")

            parsed["_usage"] = _sum_usage(usage_records)
            return parsed

        except (json.JSONDecodeError, ValueError) as exc:
            last_error = (
                f"{exc}\n原始内容前 300 字符：{last_raw[:300]}"
            )

    raise LLMError(
        f"JSON 输出连续 {max_retries} 次解析失败：{last_error}"
    )

def _sum_usage(usage_records: list) -> dict:
    total = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }

    for usage in usage_records:
        total["prompt_tokens"] += usage.get("prompt_tokens", 0)
        total["completion_tokens"] += usage.get("completion_tokens", 0)
        total["total_tokens"] += usage.get("total_tokens", 0)

    return total