# AstrBot Plugin: Gemini 2.5 Flash Image (Official API)

功能：使 QQ 机器人具备“画图/改图”能力。基于 Google Gemini 官方 API（`https://generativelanguage.googleapis.com`），支持多 Key 轮换与最大重试，生成的图片先保存到本机，再由 AstrBot 适配器上传到 QQ 群，最后自动删除本地图片（可配置）。

## 配置

在 AstrBot 插件配置中填写：

- `api_keys`: 多个 Google API Key（推荐），将自动轮询切换
- `api_key`: 单个 Key（兼容项，有 `api_keys` 时忽略）
- `api_base`: 默认 `https://generativelanguage.googleapis.com`
- `api_version`: 默认 `v1beta`
- `model_name`: 默认 `gemini-2.5-flash-image-preview`
- `max_retries`: 每个 Key 的最大重试次数（默认 3）
- `cleanup_minutes`: 历史图片自动清理的分钟数（默认 15）
- `delete_after_send`: 是否在发送后删除本地文件（默认 true）
- `delete_delay_seconds`: 删除前的延迟秒数（默认 15）

保存后重启/热加载插件生效。

## 使用

LLM 工具名：`gemini-pic-gen`

参数：
- `prompt` (str): 图像生成/编辑描述
- `use_reference_images` (bool): 是否使用消息或引用消息中的图片作为参考（默认 true）

当消息中带图或引用包含图片时，插件会将这些图片作为输入一并提交给 Gemini，用于“改图/基于图生成”。

## 行为

- 图片保存在插件目录下的 `images/` 里，文件名包含时间戳。
- 发送消息时优先尝试 `callback_api_base`（若 AstrBot 全局配置了）将本地文件转成 URL；失败时退回为本地文件发送。
- 消息发出后，若开启 `delete_after_send`，会在 `delete_delay_seconds` 后删除本地文件，避免占用磁盘空间。

## 注意

- 官方 API 模型与版本可能变化，若遇到 404/400 等，请尝试调整 `api_version` 或 `model_name`。
- 若返回报错 `RESOURCE_EXHAUSTED/429/403`，插件会自动切换下一个 Key。
- 其他错误将按 `max_retries` 对当前 Key 进行重试，并带指数退避。

## 文件结构

```
gemini_25_flash_image/
├── main.py
├── metadata.yaml
├── _conf_schema.json
├── README.md
└── utils/
    └── gemini_api.py
```

## 版权

本插件示例代码由你在本地私有环境中使用，不附带任何第三方依赖的许可证文本。Google API 的使用需遵守 Google 的服务条款与使用政策。
