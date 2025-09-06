# AstrBot 插件：Gemini 2.5 Flash Image（官方 API）

功能：让机器人具备“画图/改图”能力。基于 Google Gemini 官方 API（`https://generativelanguage.googleapis.com`），支持多 Key 轮换与最大重试。生成的图片先保存到本机，再由 AstrBot 适配器上传到平台，发送后可自动删除本地图片（可配置）。

## 安装与部署

- 将本项目放入 AstrBot 的插件目录：`AstrBot/data/plugins/gemini_25_flash_image`
- 启动 AstrBot（建议开启热重载）：`uv run -m astrbot.cli run -r`
- AstrBot 仪表盘默认端口：`http://localhost:6185`

如使用 Release 包，解压后将 `gemini_25_flash_image/` 目录放入上述路径即可。

## 配置

在 AstrBot 仪表盘 → 插件 → 本插件配置中填写：

- `api_keys`：多个 Google API Key（推荐），自动轮换
- `api_key`：单个 Key（兼容项；配置了 `api_keys` 时忽略）
- `api_base`：默认 `https://generativelanguage.googleapis.com`
- `api_version`：默认 `v1beta`
- `model_name`：默认 `gemini-2.5-flash-image-preview`
- `max_retries`：每个 Key 的最大重试次数（默认 3）
- `cleanup_minutes`：历史图片自动清理的分钟数（默认 15）
- `delete_after_send`：消息发送后删除本地文件（默认 true）
- `delete_delay_seconds`：删除前的延迟秒数（默认 15）

可选（全局配置）：`callback_api_base`。配置后发送图片会尝试将本地文件注册为可访问的 URL，提高发送兼容性。

保存后即可生效（启用热重载时无需重启）。

## 使用方法

- 画图：在聊天中发送 “/画图 一只在海边看日出的猫，水彩风”
- 改图：附带或引用一张图片，并发送 “/改图 把画面调成赛博朋克风”

说明：
- 识别命令包括前缀与中文：`/画图`、`画图`、`/改图`、`改图`
- 若消息中带图或引用包含图片，插件会将这些图片作为参考输入一并提交给 Gemini

LLM 工具：`gemini-pic-gen`
- `prompt` (str)：图像生成/编辑描述
- `use_reference_images` (bool)：是否使用消息或引用消息中的图片作为参考（默认 true）

## 行为说明

- 生成的图片保存在 `images/` 目录，文件名包含时间戳
- 若配置了 `callback_api_base`，会尝试将本地文件注册为 URL；失败时回退为本地文件发送
- 若开启 `delete_after_send`，会在 `delete_delay_seconds` 秒后删除本地文件，避免占用磁盘

## 注意事项

- 官方 API 的模型与版本可能变化，若遇到 404/400，请尝试调整 `api_version` 或 `model_name`
- 若返回 `RESOURCE_EXHAUSTED/429/403`，插件会自动轮换下一把 Key
- 其他错误会按 `max_retries` 重试并带指数退避
- 需要能够访问 `generativelanguage.googleapis.com`

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

本插件示例代码供本地私有环境使用；Google API 的使用需遵守 Google 的服务条款与使用政策。

