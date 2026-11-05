# Provider configuration

Router and answer roles are independent:

```env
ROUTER_PROVIDER=groq
ROUTER_MODEL=openai/gpt-oss-120b
ROUTER_API_BASE=https://api.groq.com/openai/v1
ROUTER_API_KEY=...
ANSWER_PROVIDER=groq
ANSWER_MODEL=openai/gpt-oss-120b
ANSWER_API_BASE=https://api.groq.com/openai/v1
ANSWER_API_KEY=...
```

For NVIDIA, OpenRouter, or another LiteLLM-supported provider, change only the corresponding role variables. For an OpenAI-compatible endpoint, set its provider/model/base URL as documented by that endpoint. These are configuration patterns; model entitlement and exact identifiers must be verified with a safe staging request.

`*_LITELLM_PARAMS` accepts a JSON object but rejects adapter-owned fields such as `model`, `messages`, `api_key`, `timeout`, `stream`, and `response_format`. Credentials are never persisted by admin settings routes.

Embedding configuration is separate. Changing `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, preprocessing, or output dimension changes the embedding fingerprint and requires a tenant-scoped re-embedding. LLM provider changes do not.
