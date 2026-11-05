"""Tenant-specific assistant identity and safe identity responses."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AssistantIdentity:
    assistant_name: str
    business_name: str
    description: str
    instructions: str


def _first(config: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def resolve_identity(client: dict[str, Any]) -> AssistantIdentity:
    config = client.get("config") or {}
    business_name = _first(config, "business_name", "businessName", "brand_name", "brandName") or str(client.get("name") or "this business").strip()
    assistant_name = _first(config, "assistant_name", "assistantName") or f"{business_name} Assistant"
    description = _first(config, "assistant_description", "assistantDescription")
    instructions = _first(config, "identity_instructions", "identityInstructions")
    return AssistantIdentity(assistant_name, business_name, description, instructions)


def identity_system_context(identity: AssistantIdentity) -> str:
    description = f" Description: {identity.description}" if identity.description else ""
    instructions = f" Additional identity instructions: {identity.instructions}" if identity.instructions else ""
    return (
        f"You are {identity.assistant_name}, the customer-facing assistant for {identity.business_name}.{description}"
        " Use this identity consistently across every response. Never identify yourself as ChatGPT, GPT, OpenAI,"
        " Groq, Gemini, or another underlying model/provider. If asked about the underlying technology, answer truthfully"
        " without replacing your customer-facing identity. Do not invent business facts; use configured identity only"
        " for self-introduction and use retrieved evidence for business claims."
        f"{instructions}"
    )


def is_identity_question(message: str, identity: AssistantIdentity | None = None) -> bool:
    text = " ".join(message.casefold().split())
    generic = (
        r"^(who are you|who is this assistant|what(?:'s| is) your name|what can you help me with|"
        r"introduce yourself|tell me about yourself|are you chatgpt|aap kaun ho|aap koun ho|tum kaun ho|ap kon ho|आप कौन हो|आपका नाम क्या है)[?.!\s]*$"
    )
    if re.fullmatch(generic, text):
        return True
    if identity:
        brand = re.escape(identity.business_name.casefold())
        assistant = re.escape(identity.assistant_name.casefold())
        return bool(
            re.search(rf"\bwho\s+is\s+(?:this\s+)?(?:{brand}|{assistant})\b", text)
            or re.search(rf"\bwhat\s+is\s+(?:{brand}|{assistant})\b", text)
        )
    return False


def identity_response(message: str, identity: AssistantIdentity) -> str:
    text = message.casefold()
    if any(token in text for token in ("aap", "kaun", "koun", "आप", "तुम")):
        return f"मैं {identity.assistant_name} हूँ, {identity.business_name} के लिए आपका सहायक।"
    if "help" in text and identity.description:
        return f"I’m {identity.assistant_name}, the assistant for {identity.business_name}. I can help with {identity.description}."
    if "name" in text:
        return f"My name is {identity.assistant_name}. I’m the assistant for {identity.business_name}."
    return f"I’m {identity.assistant_name}, the assistant for {identity.business_name}. How can I help?"


def business_name_in_message(message: str, identity: AssistantIdentity) -> bool:
    words = re.findall(r"[a-z0-9]+", identity.business_name.casefold())
    text = message.casefold()
    return bool(words and all(re.search(rf"\b{re.escape(word)}\b", text) for word in words))
