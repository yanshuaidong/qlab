---
title: Responses API
source: https://api-docs.deepseek.com/zh-cn/api/create-response
fetched: 2026-09-19
---

# Responses API

> 来源：[https://api-docs.deepseek.com/zh-cn/api/create-response](https://api-docs.deepseek.com/zh-cn/api/create-response)

```
POST /responses
```

以 OpenAI Responses API 格式创建模型响应。

该 API 是**无状态**的：服务端不存储响应与会话。多轮对话需要客户端在每次请求的 `input` 中回传完整对话历史。详细说明（含完整的参数兼容性表）请参考 [Responses API 指南](../指南/使用ResponsesAPI.md)。

## Request

**application/json**

<details>
<summary>Body**required**</summary>

</details>

**Text input**

string

**Input item list**

Array [
typestring**Possible values:** [`message`, `function_call`, `function_call_output`, `custom_tool_call`, `custom_tool_call_output`, `reasoning`]

输入 item 的类型。对于 `message` item，如果传了 `role`，此字段可省略。`custom_tool_call` / `custom_tool_call_output` item 配合 `apply_patch` custom 工具使用。

rolestring**Possible values:** [`user`, `assistant`, `system`, `developer`]

用于 `message` item。消息作者的角色。`developer` 视同 `user`。

<details>
<summary>**content**object</summary>

用于 `message` item 时为消息内容，可以是纯字符串或 `input_text` / `output_text` / `input_image` 内容块列表。用于 `reasoning` item 时为 `reasoning_text` 内容块列表。

oneOf

- Text content
- Array of content parts

string

Array [
oneOf

- 文本内容块
- 图片内容块
- 推理文本内容块

typestringrequired**Possible values:** [`input_text`, `output_text`]

内容块的类型。

textstringrequired文本内容。

typestringrequired**Possible values:** [`input_image`]

内容块的类型，此场景下为 `input_image`。

image_urlstring图片来源，可以是图片的 `http(s)` URL（最多 8192 个字符）或 base64 编码的 data URL（`data:image/jpeg;base64,...`）。支持的格式：JPEG、PNG、GIF、WebP。与 `file_id` 互斥：两者都不传返回 `400` 错误（"input_image must have image_url or file_id"），两者都传返回 `400` 错误（"input_image cannot have both image_url and file_id"）。

detailstring**Possible values:** [`low`, `high`, `original`, `auto`]

控制图片的处理方式。`low` 将图片缩小到 512x512（更快、更省 token）；`high`、`original` 与 `auto` 保留原图。设置 `file_id` 时该字段被忽略。

file_idstring通过 [Files API](../指南/文件API.md) 上传的图片文件 ID，形如 `file-api-...`。与 `image_url` 互斥；设置 `file_id` 时 `detail` 被忽略。

typestringrequired**Possible values:** [`reasoning_text`]

内容块的类型，此场景下为 `reasoning_text`。

textstringrequired思维链文本内容。

]

</details>

call_idstring用于 `function_call` / `function_call_output` item。将函数调用与其结果配对的 ID。必须非空且唯一，且每个 `function_call` 必须有对应的 `function_call_output`。

namestring用于 `function_call` item。要调用的函数的名称。

argumentsstring用于 `function_call` item。调用函数的入参，格式为 JSON。

<details>
<summary>**output**object</summary>

用于 `function_call_output` / `custom_tool_call_output` item。工具调用的结果，可以是纯字符串或 `input_text` / `input_image` 内容块列表。

oneOf

- Text output
- Array of content parts

string

Array [
oneOf

- 文本内容块
- 图片内容块
- 推理文本内容块

typestringrequired**Possible values:** [`input_text`, `output_text`]

内容块的类型。

textstringrequired文本内容。

typestringrequired**Possible values:** [`input_image`]

内容块的类型，此场景下为 `input_image`。

image_urlstring图片来源，可以是图片的 `http(s)` URL（最多 8192 个字符）或 base64 编码的 data URL（`data:image/jpeg;base64,...`）。支持的格式：JPEG、PNG、GIF、WebP。与 `file_id` 互斥：两者都不传返回 `400` 错误（"input_image must have image_url or file_id"），两者都传返回 `400` 错误（"input_image cannot have both image_url and file_id"）。

detailstring**Possible values:** [`low`, `high`, `original`, `auto`]

控制图片的处理方式。`low` 将图片缩小到 512x512（更快、更省 token）；`high`、`original` 与 `auto` 保留原图。设置 `file_id` 时该字段被忽略。

file_idstring通过 [Files API](../指南/文件API.md) 上传的图片文件 ID，形如 `file-api-...`。与 `image_url` 互斥；设置 `file_id` 时 `detail` 被忽略。

typestringrequired**Possible values:** [`reasoning_text`]

内容块的类型，此场景下为 `reasoning_text`。

textstringrequired思维链文本内容。

]

</details>

]
**Text content**

string

**Array of content parts**

Array [
oneOf

- 文本内容块
- 图片内容块
- 推理文本内容块

typestringrequired**Possible values:** [`input_text`, `output_text`]

内容块的类型。

textstringrequired文本内容。

typestringrequired**Possible values:** [`input_image`]

内容块的类型，此场景下为 `input_image`。

image_urlstring图片来源，可以是图片的 `http(s)` URL（最多 8192 个字符）或 base64 编码的 data URL（`data:image/jpeg;base64,...`）。支持的格式：JPEG、PNG、GIF、WebP。与 `file_id` 互斥：两者都不传返回 `400` 错误（"input_image must have image_url or file_id"），两者都传返回 `400` 错误（"input_image cannot have both image_url and file_id"）。

detailstring**Possible values:** [`low`, `high`, `original`, `auto`]

控制图片的处理方式。`low` 将图片缩小到 512x512（更快、更省 token）；`high`、`original` 与 `auto` 保留原图。设置 `file_id` 时该字段被忽略。

file_idstring通过 [Files API](../指南/文件API.md) 上传的图片文件 ID，形如 `file-api-...`。与 `image_url` 互斥；设置 `file_id` 时 `detail` 被忽略。

typestringrequired**Possible values:** [`reasoning_text`]

内容块的类型，此场景下为 `reasoning_text`。

textstringrequired思维链文本内容。

]
**文本内容块**

typestringrequired**Possible values:** [`input_text`, `output_text`]

内容块的类型。

textstringrequired文本内容。

**图片内容块**

typestringrequired**Possible values:** [`input_image`]

内容块的类型，此场景下为 `input_image`。

image_urlstring图片来源，可以是图片的 `http(s)` URL（最多 8192 个字符）或 base64 编码的 data URL（`data:image/jpeg;base64,...`）。支持的格式：JPEG、PNG、GIF、WebP。与 `file_id` 互斥：两者都不传返回 `400` 错误（"input_image must have image_url or file_id"），两者都传返回 `400` 错误（"input_image cannot have both image_url and file_id"）。

detailstring**Possible values:** [`low`, `high`, `original`, `auto`]

控制图片的处理方式。`low` 将图片缩小到 512x512（更快、更省 token）；`high`、`original` 与 `auto` 保留原图。设置 `file_id` 时该字段被忽略。

file_idstring通过 [Files API](../指南/文件API.md) 上传的图片文件 ID，形如 `file-api-...`。与 `image_url` 互斥；设置 `file_id` 时 `detail` 被忽略。

**推理文本内容块**

typestringrequired**Possible values:** [`reasoning_text`]

内容块的类型，此场景下为 `reasoning_text`。

textstringrequired思维链文本内容。

**Text output**

string

**Array of content parts**

Array [
oneOf

- 文本内容块
- 图片内容块
- 推理文本内容块

typestringrequired**Possible values:** [`input_text`, `output_text`]

内容块的类型。

textstringrequired文本内容。

typestringrequired**Possible values:** [`input_image`]

内容块的类型，此场景下为 `input_image`。

image_urlstring图片来源，可以是图片的 `http(s)` URL（最多 8192 个字符）或 base64 编码的 data URL（`data:image/jpeg;base64,...`）。支持的格式：JPEG、PNG、GIF、WebP。与 `file_id` 互斥：两者都不传返回 `400` 错误（"input_image must have image_url or file_id"），两者都传返回 `400` 错误（"input_image cannot have both image_url and file_id"）。

detailstring**Possible values:** [`low`, `high`, `original`, `auto`]

控制图片的处理方式。`low` 将图片缩小到 512x512（更快、更省 token）；`high`、`original` 与 `auto` 保留原图。设置 `file_id` 时该字段被忽略。

file_idstring通过 [Files API](../指南/文件API.md) 上传的图片文件 ID，形如 `file-api-...`。与 `image_url` 互斥；设置 `file_id` 时 `detail` 被忽略。

typestringrequired**Possible values:** [`reasoning_text`]

内容块的类型，此场景下为 `reasoning_text`。

textstringrequired思维链文本内容。

]
**文本内容块**

typestringrequired**Possible values:** [`input_text`, `output_text`]

内容块的类型。

textstringrequired文本内容。

**图片内容块**

typestringrequired**Possible values:** [`input_image`]

内容块的类型，此场景下为 `input_image`。

image_urlstring图片来源，可以是图片的 `http(s)` URL（最多 8192 个字符）或 base64 编码的 data URL（`data:image/jpeg;base64,...`）。支持的格式：JPEG、PNG、GIF、WebP。与 `file_id` 互斥：两者都不传返回 `400` 错误（"input_image must have image_url or file_id"），两者都传返回 `400` 错误（"input_image cannot have both image_url and file_id"）。

detailstring**Possible values:** [`low`, `high`, `original`, `auto`]

控制图片的处理方式。`low` 将图片缩小到 512x512（更快、更省 token）；`high`、`original` 与 `auto` 保留原图。设置 `file_id` 时该字段被忽略。

file_idstring通过 [Files API](../指南/文件API.md) 上传的图片文件 ID，形如 `file-api-...`。与 `image_url` 互斥；设置 `file_id` 时 `detail` 被忽略。

**推理文本内容块**

typestringrequired**Possible values:** [`reasoning_text`]

内容块的类型，此场景下为 `reasoning_text`。

textstringrequired思维链文本内容。

**Tool choice mode**

string

**Possible values:** [`none`, `auto`, `required`]

**Named tool choice**

typestringrequired**Possible values:** [`function`]

namestringThe name of the function to call. Required when `type` is `function`.

## Responses

- 200 (No streaming)
- 200 (Streaming)

OK, 返回一个 `response` 对象。

**application/json**

- Schema
- Example (from schema)
- Example

<details>
<summary>**Schema**</summary>

</details>

```json
{
  "id": "string",
  "object": "response",
  "created_at": 0,
  "status": "in_progress",
  "error": {},
  "incomplete_details": {
    "reason": "max_output_tokens"
  },
  "model": "string",
  "output": [
    {
      "type": "message",
      "id": "string",
      "status": "in_progress",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",
          "text": "string"
        }
      ],
      "call_id": "string",
      "name": "string",
      "arguments": "string"
    }
  ],
  "usage": {
    "input_tokens": 0,
    "input_tokens_details": {
      "cached_tokens": 0
    },
    "output_tokens": 0,
    "output_tokens_details": {
      "reasoning_tokens": 0
    },
    "total_tokens": 0
  }
}
```

```json
{
  "id": "24778070-1c36-4ae0-a4bd-870afc7fc13e",
  "object": "response",
  "created_at": 1753000000,
  "status": "completed",
  "model": "deepseek-flash",
  "output": [
    {
      "type": "reasoning",
      "id": "rs_1",
      "status": "completed",
      "content": [
        {
          "type": "reasoning_text",
          "text": "The user greets me. I should reply politely."
        }
      ],
      "summary": []
    },
    {
      "type": "message",
      "id": "msg_1",
      "status": "completed",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",
          "text": "Hello! How can I help you today?",
          "annotations": []
        }
      ]
    }
  ],
  "usage": {
    "input_tokens": 22,
    "input_tokens_details": { "cached_tokens": 0 },
    "output_tokens": 29,
    "output_tokens_details": { "reasoning_tokens": 27 },
    "total_tokens": 51
  },
  "store": false,
  "parallel_tool_calls": true,
  "previous_response_id": null,
  "error": null,
  "incomplete_details": null
}
```

**Schema**

<details>
<summary>**incomplete_details**objectnullable</summary>

</details>

**Example (from schema)**

```json
{
  "id": "string",
  "object": "response",
  "created_at": 0,
  "status": "in_progress",
  "error": {},
  "incomplete_details": {
    "reason": "max_output_tokens"
  },
  "model": "string",
  "output": [
    {
      "type": "message",
      "id": "string",
      "status": "in_progress",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",
          "text": "string"
        }
      ],
      "call_id": "string",
      "name": "string",
      "arguments": "string"
    }
  ],
  "usage": {
    "input_tokens": 0,
    "input_tokens_details": {
      "cached_tokens": 0
    },
    "output_tokens": 0,
    "output_tokens_details": {
      "reasoning_tokens": 0
    },
    "total_tokens": 0
  }
}
```

**Example**

```json
{
  "id": "24778070-1c36-4ae0-a4bd-870afc7fc13e",
  "object": "response",
  "created_at": 1753000000,
  "status": "completed",
  "model": "deepseek-flash",
  "output": [
    {
      "type": "reasoning",
      "id": "rs_1",
      "status": "completed",
      "content": [
        {
          "type": "reasoning_text",
          "text": "The user greets me. I should reply politely."
        }
      ],
      "summary": []
    },
    {
      "type": "message",
      "id": "msg_1",
      "status": "completed",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",
          "text": "Hello! How can I help you today?",
          "annotations": []
        }
      ]
    }
  ],
  "usage": {
    "input_tokens": 22,
    "input_tokens_details": { "cached_tokens": 0 },
    "output_tokens": 29,
    "output_tokens_details": { "reasoning_tokens": 27 },
    "total_tokens": 51
  },
  "store": false,
  "parallel_tool_calls": true,
  "previous_response_id": null,
  "error": null,
  "incomplete_details": null
}
```

OK, 返回语义化的流式 SSE 事件序列。每个事件带有表示事件类型的 `event` 字段和递增的 `sequence_number`。最后一个事件是 `response.completed` / `response.incomplete` / `response.failed`（没有 `data: [DONE]` 消息）。完整事件列表请参考 [Responses API 指南](../指南/使用ResponsesAPI.md#streaming)。

**text/event-stream**

- Schema
- Example (from schema)
- Example

<details>
<summary>**Schema**</summary>

- Array [
- ]

</details>

```json
[
  {}
]
```

```shell
event: response.created
data: {"type": "response.created", "sequence_number": 0, "response": {"id": "...", "object": "response", "status": "in_progress", ...}}

event: response.output_item.added
data: {"type": "response.output_item.added", "sequence_number": 2, "output_index": 0, "item": {"type": "reasoning", ...}}

event: response.reasoning_text.delta
data: {"type": "response.reasoning_text.delta", "sequence_number": 4, "item_id": "rs_1", "output_index": 0, "content_index": 0, "delta": "The user"}

event: response.output_item.added
data: {"type": "response.output_item.added", "sequence_number": 9, "output_index": 1, "item": {"type": "message", "role": "assistant", ...}}

event: response.output_text.delta
data: {"type": "response.output_text.delta", "sequence_number": 11, "item_id": "msg_1", "output_index": 1, "content_index": 0, "delta": "Hello"}

event: response.completed
data: {"type": "response.completed", "sequence_number": 20, "response": {"id": "...", "object": "response", "status": "completed", "usage": {...}, ...}}
```

**Schema**

<details>
<summary>详情</summary>

- Array [
- ]

</details>

**Example (from schema)**

```json
[
  {}
]
```

**Example**

```shell
event: response.created
data: {"type": "response.created", "sequence_number": 0, "response": {"id": "...", "object": "response", "status": "in_progress", ...}}

event: response.output_item.added
data: {"type": "response.output_item.added", "sequence_number": 2, "output_index": 0, "item": {"type": "reasoning", ...}}

event: response.reasoning_text.delta
data: {"type": "response.reasoning_text.delta", "sequence_number": 4, "item_id": "rs_1", "output_index": 0, "content_index": 0, "delta": "The user"}

event: response.output_item.added
data: {"type": "response.output_item.added", "sequence_number": 9, "output_index": 1, "item": {"type": "message", "role": "assistant", ...}}

event: response.output_text.delta
data: {"type": "response.output_text.delta", "sequence_number": 11, "item_id": "msg_1", "output_index": 1, "content_index": 0, "delta": "Hello"}

event: response.completed
data: {"type": "response.completed", "sequence_number": 20, "response": {"id": "...", "object": "response", "status": "completed", "usage": {...}, ...}}
```

Loading...
