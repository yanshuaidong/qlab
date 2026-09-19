---
title: FIM 补全 API（Beta）
source: https://api-docs.deepseek.com/zh-cn/api/create-completion
fetched: 2026-09-19
---

# FIM 补全 API（Beta）

> 来源：[https://api-docs.deepseek.com/zh-cn/api/create-completion](https://api-docs.deepseek.com/zh-cn/api/create-completion)

```
POST /completions
```

FIM (Fill In the Middle) 补全 API。
用户需要设置 `base_url="https://api.deepseek.com/beta"` 来使用此功能。

## Request

**application/json**

<details>
<summary>Body**required**</summary>

</details>

**MOD1**

string

**MOD2**

Array [
string

]
## Responses

- 200

OK

**application/json**

- Schema
- Example (from schema)

<details>
<summary>**Schema**</summary>

</details>

```json
{
  "id": "string",
  "choices": [
    {
      "finish_reason": "stop",
      "index": 0,
      "logprobs": {
        "text_offset": [
          0
        ],
        "token_logprobs": [
          0
        ],
        "tokens": [
          "string"
        ],
        "top_logprobs": [
          {}
        ]
      },
      "text": "string"
    }
  ],
  "created": 0,
  "model": "string",
  "system_fingerprint": "string",
  "object": "text_completion",
  "usage": {
    "completion_tokens": 0,
    "prompt_tokens": 0,
    "prompt_tokens_details": {
      "cached_tokens": 0
    },
    "prompt_cache_hit_tokens": 0,
    "prompt_cache_miss_tokens": 0,
    "total_tokens": 0,
    "completion_tokens_details": {
      "reasoning_tokens": 0
    }
  }
}
```

**Schema**

<details>
<summary>**choices**object[]required</summary>

</details>

**Example (from schema)**

```json
{
  "id": "string",
  "choices": [
    {
      "finish_reason": "stop",
      "index": 0,
      "logprobs": {
        "text_offset": [
          0
        ],
        "token_logprobs": [
          0
        ],
        "tokens": [
          "string"
        ],
        "top_logprobs": [
          {}
        ]
      },
      "text": "string"
    }
  ],
  "created": 0,
  "model": "string",
  "system_fingerprint": "string",
  "object": "text_completion",
  "usage": {
    "completion_tokens": 0,
    "prompt_tokens": 0,
    "prompt_tokens_details": {
      "cached_tokens": 0
    },
    "prompt_cache_hit_tokens": 0,
    "prompt_cache_miss_tokens": 0,
    "total_tokens": 0,
    "completion_tokens_details": {
      "reasoning_tokens": 0
    }
  }
}
```

Loading...
