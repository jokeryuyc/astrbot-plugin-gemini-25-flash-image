from astrbot.api.event import AstrMessageEvent, filter, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.all import *  # Image, Plain, llm_tool, etc.
from astrbot.core.message.components import Reply

from .utils.gemini_api import generate_image_google, schedule_delete_file


@register(
    "gemini-25-flash-image-google",
    "You",
    "使用 Google Gemini 官方 API（gemini-2.5-flash-image-preview）进行画图/改图",
    "0.1.2",
)
class GeminiImagePlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)

        # API keys: multi-key rotation
        self.api_keys = config.get("api_keys", []) or []
        old_api_key = config.get("api_key")
        if old_api_key and not self.api_keys:
            self.api_keys = [old_api_key]

        # API settings
        self.api_base = (config.get("api_base") or "https://generativelanguage.googleapis.com").rstrip("/")
        self.api_version = (config.get("api_version") or "v1beta").strip()
        self.model_name = (config.get("model_name") or "gemini-2.5-flash-image-preview").strip()

        # Retry & cleanup settings
        self.max_retries = int(config.get("max_retries", 3))
        self.cleanup_minutes = int(config.get("cleanup_minutes", 15))
        self.delete_after_send = bool(config.get("delete_after_send", True))
        self.delete_delay_seconds = int(config.get("delete_delay_seconds", 15))

    async def send_image_component(self, image_path: str) -> Image:
        """Send image, preferring callback_api_base to convert to URL when configured."""
        callback_api_base = self.context.get_config().get("callback_api_base")
        if not callback_api_base:
            return Image.fromFileSystem(image_path)
        try:
            local_comp = Image.fromFileSystem(image_path)
            # AstrBot 提供的注册到文件服务的方法名称为 register_to_file_service
            web_url = await local_comp.register_to_file_service()
            return Image.fromURL(web_url)
        except Exception as e:
            logger.warning(f"callback_api_base conversion failed, fallback to file: {e}")
            return Image.fromFileSystem(image_path)

    # ===== 快捷命令：画图/改图 =====
    def _extract_plain_text(self, event: AstrMessageEvent) -> str:
        text_parts = []
        try:
            # 使用 AstrBot 官方 API 读取消息链
            for comp in (event.get_messages() or []):
                if isinstance(comp, Plain):
                    val = getattr(comp, "text", None)
                    text_parts.append(val if isinstance(val, str) else str(comp))
        except Exception as e:
            logger.debug(f"extract text failed: {e}")
        return "".join(text_parts).strip()

    def _strip_command_prefix(self, text: str) -> str:
        if not text:
            return ""
        # 支持中英文命令，允许带/或不带/
        aliases = [
            "画图", "改图", "draw", "edit",
            "/画图", "/改图", "/draw", "/edit",
        ]
        t = text.strip()
        for a in aliases:
            if t.startswith(a):
                # 去掉命令与常见分隔符
                rest = t[len(a):].lstrip().lstrip(":：,，?？ ")
                return rest.strip()
        return t

    # 在行为面板展示为 /画图 与 /draw（AstrBot 会自动加 wake_prefix）
    @filter.command("画图", alias={"draw"})
    async def cmd_draw(self, event: AstrMessageEvent) -> MessageEventResult:
        # 我们自己处理该事件，不再让默认 LLM 流程继续
        try:
            event.stop_event()
        except Exception:
            pass
        prompt = self._strip_command_prefix(self._extract_plain_text(event))
        if not prompt:
            yield event.chain_result([Plain("用法：画图 描述文本。可附带图片作为参考")])
            return
        async for res in self.pic_gen(event, prompt, True):
            yield res

    @filter.command("改图", alias={"edit"})
    async def cmd_edit(self, event: AstrMessageEvent) -> MessageEventResult:
        try:
            event.stop_event()
        except Exception:
            pass
        prompt = self._strip_command_prefix(self._extract_plain_text(event))
        if not prompt:
            yield event.chain_result([Plain("用法：改图 描述文本，并附带或引用图片")])
            return
        async for res in self.pic_gen(event, prompt, True):
            yield res

    async def pic_gen(self, event: AstrMessageEvent, prompt: str, use_reference_images: bool = True):
        """内部实现：根据提示词与可选参考图生成/改图。"""
        if not self.api_keys:
            yield event.chain_result([Plain("未配置 Gemini API Key。请在插件配置中设置 api_keys")])
            return

        input_images_b64: list[str] = []

        if use_reference_images:
            try:
                # 当前消息中的图片
                for comp in (event.get_messages() or []):
                    if isinstance(comp, Image):
                        try:
                            b64 = await comp.convert_to_base64()
                            input_images_b64.append(b64)
                        except Exception as e:
                            logger.warning(f"convert current message image to b64 failed: {e}")
                    elif isinstance(comp, Reply):
                        for reply_comp in comp.chain or []:
                            if isinstance(reply_comp, Image):
                                try:
                                    b64 = await reply_comp.convert_to_base64()
                                    input_images_b64.append(b64)
                                except Exception as e:
                                    logger.warning(f"convert quoted image to b64 failed: {e}")
            except Exception as e:
                logger.warning(f"collect reference images failed: {e}")

        try:
            image_path = await generate_image_google(
                prompt=prompt,
                api_keys=self.api_keys,
                model=self.model_name,
                api_base=self.api_base,
                api_version=self.api_version,
                input_images=input_images_b64,
                max_retries=self.max_retries,
                cleanup_minutes=self.cleanup_minutes,
            )

            if not image_path:
                yield event.chain_result([Plain("图像生成失败，请稍后重试或更换 API Key")])
                return

            comp = await self.send_image_component(image_path)
            yield event.chain_result([comp])

            if self.delete_after_send:
                schedule_delete_file(image_path, delay_seconds=self.delete_delay_seconds)

        except Exception as e:
            logger.error(f"Gemini image generation error: {e}")
            yield event.chain_result([Plain(f"图像生成失败: {str(e)}")])

    @llm_tool(name="gemini-pic-gen")
    async def tool_pic_gen(self, event: AstrMessageEvent, prompt: str = "", use_reference_images: bool = True):
        """使用 Gemini 官方图像模型生成/改图。

        Args:
            prompt(string): 文本提示（必填）
            use_reference_images(boolean): 是否使用消息或引用消息中的图片作为参考（默认 true）
        """
        prompt = prompt if isinstance(prompt, str) else str(prompt)
        async for res in self.pic_gen(event, prompt, use_reference_images):
            yield res
