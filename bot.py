#!/usr/bin/env python3
import asyncio
import math
import struct
import sys
import time

PI = math.pi
M_2PI = 2.0 * PI

PROTOCOL_VERSION = 30
CLIENT_VERSION = 291
PING_BYTE = 251


def normalize_angle(ang):
    return ang - M_2PI * math.floor(ang / M_2PI)


def read_uint16_be(data, offset=0):
    return struct.unpack_from('>H', data, offset)[0], offset + 2


def encode_name(name):
    s = name.encode('ascii', errors='replace')[:24]
    cv = 5
    cpw = bytes([54, 206, 204, 169, 97, 178, 74, 136, 124, 117, 14,
                 210, 106, 236, 8, 208, 136, 213, 140, 111])
    return cpw + bytes([cv, len(s)]) + s + bytes([0, 255])


def js_mod(a, b):
    if a >= 0:
        return a % b
    return -(abs(a) % b)


def decode_server_version(data):
    a = ""
    d = 0
    e = 23
    f = 0
    for g in range(len(data)):
        b = data[g]
        if b <= 96:
            b += 32
        b = (b - 97 - e) % 26
        if b < 0:
            b += 26
        d = d * 16 + b
        e += 17
        if f == 1:
            a += chr(d)
            f = 0
            d = 0
        else:
            f += 1
    return a


def extract_seed(js):
    q1 = js.find('"')
    if q1 < 0:
        raise ValueError("Cannot find seed in JS")
    q2 = js.find('"', q1 + 1)
    part1 = js[q1 + 1:q2]
    q3 = js.find('"', q2 + 1)
    q4 = js.find('"', q3 + 1)
    part2 = js[q3 + 1:q4]
    return part1 + part2


def qff9x_transform(seed_str):
    out = [ord(c) for c in seed_str]
    roll = 0
    for c in range(len(out)):
        base = 65
        a = out[c]
        if a >= 97:
            base += 32
            a -= 32
        a -= 65
        if c == 0:
            roll = 3 + a
        e = js_mod(a + roll, 26)
        roll += 4 + a
        out[c] = e + base
    return bytes(out)


def solve_challenge(challenge_bytes):
    if len(challenge_bytes) > 27:
        js = decode_server_version(challenge_bytes[1:])
        if js.startswith('var a'):
            seed = extract_seed(js)
            return qff9x_transform(seed)
    js = decode_server_version(challenge_bytes)
    seed = extract_seed(js)
    return qff9x_transform(seed)


class Bot:
    def __init__(self, ws, name, game_radius=21600, fixed_heading=None):
        self.ws = ws
        self.name = name
        self.game_radius = game_radius
        self.snake_id = 0
        self.x = game_radius
        self.y = game_radius
        self.wangle = 0.0
        self.fixed_heading = fixed_heading

    def steer(self):
        if self.fixed_heading is not None:
            aim = self.fixed_heading
        else:
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


async def run_bot(name, host, port, path, fixed_heading=None):
    import websockets

    headers = {
        "Origin": "http://slither.com",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
    }

    while True:
        try:
            uri = f"ws://{host}:{port}{path}"
            async with websockets.connect(uri, ping_interval=None, max_size=2**20,
                                          additional_headers=headers, open_timeout=10) as ws:
                bot = Bot(ws, name, fixed_heading=fixed_heading)
                print(f"[{name}] Connected, sending handshake...", flush=True)

                await ws.send(bytes([1]))
                await ws.send(bytes([99, 0]))

                challenge = None
                try:
                    challenge = await asyncio.wait_for(ws.recv(), timeout=3)
                    print(f"[{name}] Got challenge ({len(challenge)}B)", flush=True)
                except asyncio.TimeoutError:
                    print(f"[{name}] No challenge received, proceeding...", flush=True)

                if challenge:
                    response = solve_challenge(challenge)
                    await ws.send(response)

                name_data = encode_name(bot.name)
                cv_h = CLIENT_VERSION >> 8
                cv_l = CLIENT_VERSION & 255
                username_pkt = bytes([ord('s'), PROTOCOL_VERSION, cv_h, cv_l]) + name_data
                await ws.send(username_pkt)

                init = await asyncio.wait_for(ws.recv(), timeout=10)
                if not isinstance(init, bytes) or len(init) < 4:
                    print(f"[{name}] Bad init packet", flush=True)
                    continue

                found_id = False
                last_ping = time.monotonic()
                last_cord_log = time.monotonic()

                while True:
                    now = time.monotonic()
                    if now - last_cord_log > 1:
                        print(f"[{name}] x={bot.x} y={bot.y}", flush=True)
                        last_cord_log = now
                    if now - last_ping > 0.25:
                        await ws.send(bytes([PING_BYTE]))
                        last_ping = now

                    angle_byte = bot.steer()
                    if angle_byte is not None:
                        await ws.send(bytes([angle_byte]))

                    for _ in range(5):
                        try:
                            d = await asyncio.wait_for(ws.recv(), timeout=0.02)
                            if len(d) < 3:
                                continue
                            ptype = d[2]
                            if ptype == ord('s') and len(d) >= 5:
                                sid, _ = read_uint16_be(d, 3)
                                if not found_id:
                                    bot.snake_id = sid
                                    found_id = True
                            if found_id and ptype == ord('g') and len(d) >= 9:
                                sid, _ = read_uint16_be(d, 3)
                                if sid == bot.snake_id:
                                    x, _ = read_uint16_be(d, 5)
                                    y, _ = read_uint16_be(d, 7)
                                    if x > 0 or y > 0:
                                        bot.x = x
                                        bot.y = y
                        except asyncio.TimeoutError:
                            break

                    await asyncio.sleep(0.04)

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[{name}] Disconnected ({e}), reconnecting in 3s...", flush=True)
            await asyncio.sleep(3)


async def main():
    print("slither.io Bot Client")
    print("=" * 35)

    host = input("Server IP (default 192.211.52.146): ").strip() or "192.211.52.146"
    port_str = input("Server port (default 444): ").strip() or "444"
    try:
        port = int(port_str)
    except ValueError:
        print("Invalid port, using 444")
        port = 444

    path = input("Path (default /slither): ").strip() or "/slither"
    if not path.startswith("/"):
        path = "/" + path

    count_str = input("Number of bots: ").strip() or "1"
    try:
        count = max(1, int(count_str))
    except ValueError:
        count = 1

    print(f"\nSpawning {count} bot(s) -> ws://{host}:{port}{path}\n")

    tasks = []
    for i in range(count):
        name = f"Bot_{i + 1}"
        heading = None
        if i == 0:
            heading = 0.5
        elif i == 1:
            heading = 3.8
        tasks.append(asyncio.create_task(run_bot(name, host, port, path, fixed_heading=heading)))
        await asyncio.sleep(1.5)

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
