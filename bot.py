#!/usr/bin/env python3
import asyncio
import math
import struct
import sys
import time

PI = math.pi
M_2PI = 2.0 * PI


def normalize_angle(ang):
    return ang - M_2PI * math.floor(ang / M_2PI)


def read_uint16(data, offset=0):
    return struct.unpack_from('!H', data, offset)[0], offset + 2


class Bot:
    def __init__(self, ws, name, game_radius=21600):
        self.ws = ws
        self.name = name
        self.game_radius = game_radius
        self.snake_id = 0
        self.x = game_radius
        self.y = game_radius
        self.wangle = 0.0

    def steer(self):
        dx = self.game_radius - self.x
        dy = self.game_radius - self.y
        dist = math.hypot(dx, dy)
        if dist < 200:
            return None
        aim = math.atan2(dy, dx)
        aim = normalize_angle(aim)
        if abs(self.wangle - aim) > 0.01:
            self.wangle = aim
        return max(0, min(250, int(self.wangle * 125.0 / PI)))


async def run_bot(name, host, port, path="/"):
    import websockets

    async def try_connect(scheme):
        uri = f"{scheme}://{host}:{port}{path}"
        async with websockets.connect(uri, ping_interval=None, max_size=2**20) as ws:
            bot = Bot(ws, name)
            connected = await asyncio.wait_for(ws.recv(), timeout=10)
            if not isinstance(connected, bytes) or len(connected) < 3:
                return
            if connected[2] == ord('a') and len(connected) >= 6:
                gr = struct.unpack('!I', b'\x00' + connected[3:6])[0]
                bot.game_radius = gr

            await ws.send(bytes([ord('s'), 8, len(name)]) + name.encode())

            found_id = False
            last_ping = time.monotonic()

            while True:
                now = time.monotonic()
                if now - last_ping > 0.25:
                    await ws.send(bytes([251]))
                    last_ping = now

                angle_byte = bot.steer()
                if angle_byte is not None:
                    await ws.send(bytes([angle_byte]))

                for _ in range(5):
                    try:
                        d = await asyncio.wait_for(ws.recv(), timeout=0.02)
                        if not isinstance(d, bytes) or len(d) < 3:
                            continue
                        ptype = d[2]
                        if ptype == ord('s') and len(d) >= 5:
                            sid, _ = read_uint16(d, 3)
                            if not found_id:
                                bot.snake_id = sid
                                found_id = True
                        if found_id and ptype == ord('g') and len(d) >= 9:
                            sid, _ = read_uint16(d, 3)
                            if sid == bot.snake_id:
                                x, _ = read_uint16(d, 5)
                                y, _ = read_uint16(d, 7)
                                if x > 0 or y > 0:
                                    bot.x = x
                                    bot.y = y
                    except asyncio.TimeoutError:
                        break

                await asyncio.sleep(0.04)

    try:
        await try_connect("ws")
    except Exception:
        try:
            await try_connect("wss")
        except Exception as e:
            print(f"[{name}] {e}", flush=True)


async def main():
    print("slither.io Bot Client")
    print("=" * 35)

    host = input("Server IP (default 127.0.0.1): ").strip() or "127.0.0.1"
    port_str = input("Server port (default 8080): ").strip() or "8080"
    try:
        port = int(port_str)
    except ValueError:
        print("Invalid port, using 8080")
        port = 8080

    path = input("Path (default /): ").strip() or "/"
    if not path.startswith("/"):
        path = "/" + path

    count_str = input("Number of bots: ").strip() or "1"
    try:
        count = max(1, int(count_str))
    except ValueError:
        count = 1

    scheme = "ws"
    print(f"\nSpawning {count} bot(s) -> {scheme}://{host}:{port}{path}\n")

    tasks = []
    for i in range(count):
        name = f"Bot_{i + 1}"
        tasks.append(asyncio.create_task(run_bot(name, host, port, path)))
        await asyncio.sleep(0.15)

    print(f"{count} bot(s) running. Press Ctrl+C to stop.\n")

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(0)
