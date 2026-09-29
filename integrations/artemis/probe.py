"""Read-only live Ghost capture probe. No start, launch, wake or input commands."""
import argparse
import asyncio
import json
from pathlib import Path

from ghost_bridge import CommandTransport, GhostSession


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    endpoint = parser.add_mutually_exclusive_group(required=True)
    endpoint.add_argument('--serial', help='Explicit ADB device serial')
    endpoint.add_argument('--ssh', help='Already trusted/authenticated SSH user@host')
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--ssh-executable', default='ssh')
    parser.add_argument('--port', type=int, default=8022)
    parser.add_argument('--out', type=Path, required=True, help='Private local PNG destination')
    args = parser.parse_args()
    transport = (CommandTransport.adb(args.adb, args.serial) if args.serial else
                 CommandTransport.ssh(args.ssh_executable, args.ssh, args.port))
    session = GhostSession(transport)
    frame = await session.observe()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(frame.image)
    print(json.dumps(dict(ok=True, displayId=frame.display_id, width=frame.width,
                          height=frame.height, path=str(args.out.resolve()), inputsSent=0)))


if __name__ == '__main__':
    asyncio.run(main())
