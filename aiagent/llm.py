from openai import OpenAI
import time
from openai import APIStatusError
class LLMClient:
    def __init__(self, base_url, api_key, model, max_tokens, temperature):
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_retries = 3

    def _should_retry(self, error, attempt):
        if isinstance(error, APIStatusError):
            if error.status_code < 500 and error.status_code != 429:
                return False
        if attempt >= self.max_retries - 1:
            return False
        return True

    def chat(self, messages, tools=None):
        kwargs = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        for attempt in range(self.max_retries):
            try:
                response = self.client.chat.completions.create(**kwargs)
                break
            except Exception as e:
                if not self._should_retry(e, attempt):
                    raise
                print(f"\n⚠️ API 调用失败 (第 {attempt+1}/{self.max_retries} 次): {e}")
                time.sleep(2 ** attempt)  # 指数退避

        message = response.choices[0].message
        tool_calls = None
        if message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                }
                for tc in message.tool_calls
            ]

        return {
            "content": message.content,
            "tool_calls": tool_calls,
            "reasoning": getattr(message, "reasoning_content", None),
            "usage": {
                    "input": response.usage.prompt_tokens if response.usage else 0,
                    "output": response.usage.completion_tokens if response.usage else 0
                   },
            "finish_reason": response.choices[0].finish_reason or "stop"
        }
    
    def stream_chat(self, messages, tools=None, on_delta=None):
        content_parts = []
        reasoning_parts = []
        tool_calls_acc = {}
        tool_gen_notified = set()
        finish_reason = None
        usage = None
        kwargs = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": True,
            "stream_options": {"include_usage": True}
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        for attempt in range(self.max_retries):
            try:
                stream = self.client.chat.completions.create(**kwargs)
                break
            except Exception as e:
                if not self._should_retry(e, attempt):
                    raise
                print(f"\n⚠️ API 调用失败 (第 {attempt+1}/{self.max_retries} 次): {e}")
                time.sleep(2 ** attempt)  # 指数退避
        for chunk in stream:
            if hasattr(chunk, "usage") and chunk.usage:
                usage = {"input": chunk.usage.prompt_tokens, "output": chunk.usage.completion_tokens}
            if not chunk.choices:
                if hasattr(chunk, "usage") and chunk.usage:
                    usage = {"input": chunk.usage.prompt_tokens, "output": chunk.usage.completion_tokens}
                continue

            delta = chunk.choices[0].delta

            r = getattr(delta, "reasoning_content", None)
            if r:
                reasoning_parts.append(r)
                if on_delta:
                    on_delta({"type": "reasoning", "text": r})
            
            if delta.content:
                content_parts.append(delta.content)
                if on_delta and not tool_calls_acc:
                    on_delta({"type": "content", "text": delta.content})
               
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index if tc.index is not None else 0
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {
                            "id": "",
                            "type": "function",
                            "function": {
                                "name": "",
                                "arguments": ""
                            }
                        }
                    entry = tool_calls_acc[idx]
                    if tc.id:
                        entry["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            entry["function"]["name"] = tc.function.name
                            name = entry["function"]["name"]
                            if name and idx not in tool_gen_notified:
                                tool_gen_notified.add(idx)
                                if on_delta:
                                    on_delta({"type": "tool_start", "name": name})
                        if tc.function.arguments:
                            entry["function"]["arguments"] += tc.function.arguments
                                   
            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason

        tool_calls = None
        if tool_calls_acc:
             tool_calls = [
        {
            "id": tc["id"],
            "type": "function",
            "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]}
        }
        for tc in [tool_calls_acc[i] for i in sorted(tool_calls_acc)]
    ]
             
        return {
            "content": "".join(content_parts) or None,
            "tool_calls": tool_calls,
            "reasoning": "".join(reasoning_parts) or None,
            "usage": usage or {"input": 0, "output": 0},
            "finish_reason": finish_reason or "stop"
        }

            

        