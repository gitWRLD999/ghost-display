"""Ghost-only transport and observation guards; no Artemis dependency required."""
from __future__ import annotations

import asyncio
import json
import shlex
import struct
from dataclasses import dataclass


class GhostError(RuntimeError):
    pass


class CommandTransport:
    """A fixed adb serial or authenticated SSH endpoint. Never runs a shell on PC."""

    def __init__(self, prefix: list[str], remote_prefix: str):
        self.prefix = prefix
        self.remote_prefix = remote_prefix

    @classmethod
    def adb(cls, executable: str, serial: str):
        if not serial or serial.startswith("-"):
            raise ValueError("An explicit ADB serial is required")
        return cls([executable, "-s", serial, "exec-out"], "sh /data/local/tmp/ghostctl")

    @classmethod
    def ssh(cls, executable: str, destination: str, port: int = 8022):
        if not destination or destination.startswith("-") or not 1 <= port <= 65535:
            raise ValueError("An explicit SSH destination and valid port are required")
        return cls([executable, "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                    "-o", "ConnectTimeout=5", "-p", str(port), destination], "$HOME/bin/ghostctl")

    async def run(self, *args: str) -> bytes:
        remote = self.remote_prefix + " " + " ".join(shlex.quote(str(a)) for a in args)
        proc = await asyncio.create_subprocess_exec(
            *self.prefix, remote, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), 15)
        except (TimeoutError, asyncio.CancelledError):
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            raise GhostError("Transport interrupted; command outcome unknown. Observe before retrying.")
        if proc.returncode:
            raise GhostError(err.decode("utf-8", errors="replace")[:1000] or "ghostctl failed")
        return out


@dataclass(frozen=True)
class Observation:
    image: bytes
    width: int
    height: int
    display_id: int
    generation: tuple


class GhostSession:
    """Requires a fresh observation before input and after display recovery/resize."""

    SAFE_KEYS = frozenset({"ENTER", "DEL", "TAB", "ESCAPE", "DPAD_UP", "DPAD_DOWN",
                           "DPAD_LEFT", "DPAD_RIGHT", "DPAD_CENTER", "MOVE_HOME", "MOVE_END"})

    def __init__(self, transport, allowed_packages=(), max_actions: int = 40):
        if max_actions < 1:
            raise ValueError("max_actions must be positive")
        self.transport = transport
        self.allowed_packages = frozenset(allowed_packages)
        self.max_actions = max_actions
        self.actions = 0
        self.observed = None
        self.lock = asyncio.Lock()

    async def _json(self, *args):
        try:
            result = json.loads(await self.transport.run(*args))
        except (ValueError, TypeError) as exc:
            raise GhostError("Invalid Ghost response") from exc
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise GhostError(str(result))
        return result

    async def status(self):
        return await self._json("status", "--json")

    @staticmethod
    def generation(status):
        if status.get("running") is not True or type(status.get("displayId")) is not int or status["displayId"] <= 0:
            raise GhostError("Ghost display unavailable; physical display fallback is forbidden")
        if status.get("backendUid") != 2000 or status.get("state") != "ON":
            raise GhostError("Ghost must be ON with its shell-owned backend")
        if status.get("captureHealth") != "ready" or status.get("inputHealth") != "ok":
            raise GhostError("Ghost capture/input is not ready")
        if any(type(status.get(k)) is not int or status[k] <= 0 for k in ("width", "height", "backendPid")):
            raise GhostError("Invalid Ghost geometry/backend identity")
        return tuple(status.get(k) for k in ("displayId", "backendPid", "width", "height", "virtualDeviceId"))

    async def observe(self) -> Observation:
        async with self.lock:
            self.observed = None
            before = self.generation(await self.status())
            image = await self.transport.run("screenshot", "--format", "png")
            after = self.generation(await self.status())
            if before != after:
                raise GhostError("Display changed during capture; capture again")
            if len(image) < 24 or image[:8] != b"\x89PNG\r\n\x1a\n" or image[12:16] != b"IHDR":
                raise GhostError("Screenshot is not a PNG; no fabricated frame fallback")
            width, height = struct.unpack(">II", image[16:24])
            if (width, height) != after[2:4]:
                raise GhostError("Screenshot geometry differs from Ghost status")
            self.observed = after
            return Observation(image, width, height, after[0], after)

    async def _ready(self, expected=None):
        live = self.generation(await self.status())
        if (self.observed if expected is None else expected) != live:
            self.observed = None
            raise GhostError("Observe Ghost first; previous coordinates are stale after recovery/resize")
        if self.actions >= self.max_actions:
            raise GhostError("Action budget reached; start a new bounded session")
        return live

    @staticmethod
    def pixel(value, size):
        if type(value) is not int or not 0 <= value <= 1000:
            raise GhostError("Coordinates must be integers from 0 through 1000")
        return min(size - 1, value * size // 1000)

    @staticmethod
    def duration(value):
        if type(value) is not int or not 1 <= value <= 5000:
            raise GhostError("Duration must be 1..5000 ms")
        return str(value)

    async def _dispatch(self, command, *args):
        # A timeout consumes the budget too: the remote action might have happened.
        self.actions += 1
        try:
            return await self._json(command, *(str(a) for a in args))
        finally:
            self.observed = None

    async def click(self, nx, ny, duration_ms=None):
        async with self.lock:
            live = await self._ready()
            x, y = self.pixel(nx, live[2]), self.pixel(ny, live[3])
            if duration_ms is None:
                return await self._dispatch("tap", x, y)
            return await self._dispatch("long-press", x, y, self.duration(duration_ms))

    async def click_sequence(self, points, delay_ms=50):
        if not 1 <= len(points) <= 20 or type(delay_ms) is not int or not 0 <= delay_ms <= 2000:
            raise GhostError("Sequence requires 1..20 points and 0..2000 ms delay")
        for x, y in points:
            self.pixel(x, 1000)
            self.pixel(y, 1000)
        async with self.lock:
            expected = await self._ready()
            if self.actions + len(points) > self.max_actions:
                raise GhostError("Sequence exceeds remaining action budget")
            for index, (x, y) in enumerate(points):
                live = await self._ready(expected)
                await self._dispatch("tap", self.pixel(x, live[2]), self.pixel(y, live[3]))
                if index + 1 < len(points):
                    await asyncio.sleep(delay_ms / 1000)

    async def swipe(self, start, end, duration_ms=800):
        async with self.lock:
            live = await self._ready()
            sx, sy = self.pixel(start[0], live[2]), self.pixel(start[1], live[3])
            ex, ey = self.pixel(end[0], live[2]), self.pixel(end[1], live[3])
            return await self._dispatch("swipe", sx, sy, ex, ey, self.duration(duration_ms))

    async def text(self, text, target=None):
        if not isinstance(text, str) or len(text.encode("utf-8")) > 32000:
            raise GhostError("Text must be a string of at most 32000 UTF-8 bytes")
        async with self.lock:
            expected = await self._ready()
            if target is not None:
                x, y = self.pixel(target[0], expected[2]), self.pixel(target[1], expected[3])
                if self.actions + 2 > self.max_actions:
                    raise GhostError("Focus-and-insert exceeds remaining action budget")
                await self._dispatch("tap", x, y)
                await self._ready(expected)
            return await self._dispatch("text", text)

    async def key(self, key):
        name = str(key).upper().removeprefix("KEYCODE_")
        if name == "DELETE":
            name = "DEL"
        if name not in self.SAFE_KEYS | {"BACK", "HOME"}:
            raise GhostError("Key is not permitted: power, volume and global keys are excluded")
        async with self.lock:
            await self._ready()
            return await self._dispatch(name.lower()) if name in {"BACK", "HOME"} else await self._dispatch("key", name)

    async def launch(self, package):
        if package not in self.allowed_packages:
            raise GhostError("Package is not approved for this session; apps share the user's data/tasks")
        async with self.lock:
            await self._ready()
            if package == "com.vertex.ghost":
                return await self._dispatch("open-component", "com.vertex.ghost/.GhostTestActivity")
            return await self._dispatch("open-app", package)
