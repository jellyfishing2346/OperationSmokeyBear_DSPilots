# local_llm_provider.py
"""
Local LLM provider using Ollama with Qwen2.5 model.
Completely free and private - no data leaves your server.
"""
import os
import json
import requests
from typing import Dict, List
from .prompt import build_extraction_prompt, field_descriptions

class LLMProvider:
    def extract_fields(self, transcript: str, fields: List[str]) -> Dict[str, str]:
        raise NotImplementedError


class OllamaProvider(LLMProvider):
    """
    Local LLM provider using Ollama.
    
    Install Ollama: https://ollama.ai/
    Then run: ollama pull qwen2.5:7b
    
    This is 100% free and private - no external API calls.
    """
    def __init__(
        self,
        model_name: str = None,
        base_url: str = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ):
        # Read from environment variables if not provided
        self.model_name = model_name or os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.temperature = temperature
        self.max_tokens = max_tokens
        
    def extract_fields(self, transcript: str, fields: List[str]) -> Dict[str, dict]:
        """
        Extracts fields using local Ollama LLM.
        Returns: {"field_name": {"value": "...", "confidence": 0.x}}
        """
        prompt = build_extraction_prompt(transcript, fields, field_descriptions=field_descriptions)
        
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
            "format": "json",  # Force JSON output
        }
        
        try:
            print(f"🔍 Calling Ollama: {self.base_url}/api/generate")
            print(f"🔍 Model: {self.model_name}")
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=120  # 2 minutes max
            )
            response.raise_for_status()
            
            result = response.json()
            text = result.get("response", "").strip()
            print(f"🔍 Ollama response length: {len(text)} chars")
            print(f"🔍 First 200 chars: {text[:200]}")
            
            # Parse JSON response
            data = self._safe_json(text)
            print(f"🔍 Parsed JSON keys: {list(data.keys())[:10]}")
            results = {}
            
            for f in fields:
                entry = data.get(f, {})
                if isinstance(entry, dict):
                    val = str(entry.get("value", "")).strip()
                    conf = entry.get("confidence", 0.0)
                    
                    # Set confidence=0 if value is empty
                    if val == "":
                        conf = 0.0
                    
                    # Sanitize confidence
                    try:
                        conf = float(conf)
                    except Exception:
                        conf = 0.0
                    conf = max(0.0, min(conf, 1.0))
                    
                    results[f] = {"value": val, "confidence": conf}
                else:
                    results[f] = {"value": str(entry).strip(), "confidence": 0.0}
            
            return results
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Ollama API error: {e}")
            print("⚠️  Make sure Ollama is running: ollama serve")
            print(f"⚠️  Make sure model is installed: ollama pull {self.model_name}")
            # Return empty defaults
            return {f: {"value": "", "confidence": 0.0} for f in fields}
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            return {f: {"value": "", "confidence": 0.0} for f in fields}
    
    @staticmethod
    def _safe_json(text: str) -> dict:
        """Attempts to parse JSON safely."""
        t = (text or "").strip()
        
        # Try direct parse
        try:
            return json.loads(t)
        except Exception:
            pass
        
        # Try stripping Markdown fences
        if t.startswith("```"):
            t2 = t.strip("`")
            if t2.lower().startswith("json"):
                t2 = t2[4:].strip()
            try:
                return json.loads(t2)
            except Exception:
                pass
        
        # Try substring between first and last braces
        start, end = t.find("{"), t.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(t[start:end+1])
            except Exception:
                pass
        
        # If nothing works, return empty dict
        return {}


class VLLMProvider(LLMProvider):
    """
    Alternative: Local LLM provider using vLLM server.
    
    More efficient for high-throughput use cases.
    Install: pip install vllm
    Run: python -m vllm.entrypoints.openai.api_server --model Qwen/Qwen2.5-7B-Instruct
    """
    def __init__(
        self,
        model_name: str = "Qwen/Qwen2.5-7B-Instruct",
        base_url: str = "http://localhost:8000/v1",
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ):
        self.model_name = model_name
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens
        
    def extract_fields(self, transcript: str, fields: List[str]) -> Dict[str, dict]:
        """
        Extracts fields using vLLM server (OpenAI-compatible API).
        """
        prompt = build_extraction_prompt(transcript, fields, field_descriptions=field_descriptions)
        
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant that extracts structured incident data."},
                {"role": "user", "content": prompt}
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"}
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                timeout=120
            )
            response.raise_for_status()
            
            result = response.json()
            text = result["choices"][0]["message"]["content"].strip()
            
            # Parse JSON response
            data = self._safe_json(text)
            results = {}
            
            for f in fields:
                entry = data.get(f, {})
                if isinstance(entry, dict):
                    val = str(entry.get("value", "")).strip()
                    conf = entry.get("confidence", 0.0)
                    
                    if val == "":
                        conf = 0.0
                    
                    try:
                        conf = float(conf)
                    except Exception:
                        conf = 0.0
                    conf = max(0.0, min(conf, 1.0))
                    
                    results[f] = {"value": val, "confidence": conf}
                else:
                    results[f] = {"value": str(entry).strip(), "confidence": 0.0}
            
            return results
            
        except Exception as e:
            print(f"❌ vLLM API error: {e}")
            return {f: {"value": "", "confidence": 0.0} for f in fields}
    
    @staticmethod
    def _safe_json(text: str) -> dict:
        """Attempts to parse JSON safely."""
        t = (text or "").strip()
        
        try:
            return json.loads(t)
        except Exception:
            pass
        
        if t.startswith("```"):
            t2 = t.strip("`")
            if t2.lower().startswith("json"):
                t2 = t2[4:].strip()
            try:
                return json.loads(t2)
            except Exception:
                pass
        
        start, end = t.find("{"), t.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(t[start:end+1])
            except Exception:
                pass
        
        return {}

