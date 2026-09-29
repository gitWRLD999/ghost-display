"""Experimental Artemis actuator. Import inside a fully installed Artemis runtime."""
from __future__ import annotations

import asyncio
import base64
from io import BytesIO
from dataclasses import dataclass

from ghost_bridge import GhostError, GhostSession


@dataclass(frozen=True)
class GhostScreenData:
    base64: str
    width: int
    height: int
    platform: str = "android"
    hierarchy_available: bool = False

    @property
    def elements(self):
        # Upstream observation catches this and records hierarchy_ok=False.
        raise GhostError("Ghost UI hierarchy is unavailable; inspect the screenshot")


class GhostActuator:
    def __init__(self, session: GhostSession, ctx=None, result_type=None):
        if result_type is None:
            from artemis.mcp.action_types import ActionResult
            result_type = ActionResult
        self.result_type = result_type
        self.session = session
        self.ctx = ctx
        self.controller = self
        self.operation_lock = asyncio.Lock()

    def capabilities(self):
        return frozenset({"click_sequence", "click", "long_press", "input_text", "swipe",
                          "press_key", "manage_app", "wait_for_delay", "erase_one_char",
                          "observe_screen", "take_screenshot", "get_ui_hierarchy"})

    def extensions(self):
        return []

    async def _action(self, action, coroutine):
        try:
            async with self.operation_lock:
                await coroutine
            return self.result_type.success(action, "Ghost accepted the action; verify its effect in a fresh screenshot.")
        except (GhostError, ValueError, TypeError, IndexError) as exc:
            return self.result_type.failure(action, str(exc))
        except asyncio.CancelledError:
            coroutine.close()
            raise

    async def click_sequence(self, points, delay_ms=50):
        return await self._action("click_sequence", self.session.click_sequence(points, delay_ms))

    async def click(self, nx, ny, times=1, delay_ms=100):
        if type(times) is not int or not 1 <= times <= 20:
            return self.result_type.failure("click", "times must be 1..20")
        result = await self.click_sequence([(nx, ny)] * times, delay_ms)
        result.action = "click"
        return result

    async def long_press(self, nx, ny, duration_ms=1000):
        return await self._action("long_press", self.session.click(nx, ny, duration_ms))

    async def input_text(self, text, target=None, clear_exist=True):
        async def run():
            if clear_exist:
                raise GhostError("Full-field clearing is unsupported. Use clear_exist=false; no clipboard/global key fallback.")
            await self.session.text(text, target)
        return await self._action("input_text", run())

    async def swipe(self, start, end, duration_ms=800):
        return await self._action("swipe", self.session.swipe(start, end, duration_ms))

    async def press_key(self, key):
        return await self._action("press_key", self.session.key(key))

    async def manage_app(self, action, app_name):
        async def run():
            if action != "launch":
                raise GhostError("Force-stop affects all displays and is excluded. Only launch is supported.")
            await self.session.launch(app_name)
        return await self._action("manage_app", run())

    async def wait_for_delay(self, time_in_ms):
        async def run():
            if type(time_in_ms) is not int or not 0 <= time_in_ms <= 10000:
                raise GhostError("Wait must be 0..10000 ms")
            await asyncio.sleep(time_in_ms / 1000)
        return await self._action("wait_for_delay", run())

    async def erase_one_char(self):
        return await self._action("erase_one_char", self.session.key("DEL"))

    async def get_screen_data(self):
        async with self.operation_lock:
            observation = await self.session.observe()
            # Upstream observe_screen labels image blocks as image/jpeg and persists .jpg.
            # Decode the real PNG, then encode JPEG to match that transport contract.
            from PIL import Image
            def encode_jpeg():
                with Image.open(BytesIO(observation.image)) as image:
                    image.load()
                    destination = BytesIO()
                    image.convert("RGB").save(destination, format="JPEG", quality=85)
                    return destination.getvalue()
            try:
                jpeg = await asyncio.to_thread(encode_jpeg)
            except Exception as exc:
                self.session.observed = None
                raise GhostError("Ghost frame could not be decoded") from exc
        if self.ctx is not None and getattr(self.ctx, "device", None) is not None:
            # Upstream currently reads hierarchy before its dimension update; keep
            # dimensions fresh even when that optional hierarchy read fails.
            self.ctx.device.device_width = observation.width
            self.ctx.device.device_height = observation.height
        return GhostScreenData(base64=base64.b64encode(jpeg).decode("ascii"),
                               width=observation.width, height=observation.height)

    async def take_screenshot(self):
        return (await self.get_screen_data()).base64

    async def get_ui_elements(self):
        # Never attach display-0 Accessibility/UIAutomator nodes to a Ghost frame.
        raise GhostError("Ghost UI hierarchy is unavailable; inspect the screenshot")
