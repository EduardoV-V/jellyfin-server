#!/usr/bin/env python3

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import random
import time

HOST = "127.0.0.1"
PORT = 8283

start_time = int(time.time()) - random.randint(100000, 900000)

class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path != "/api/sysinfo/all":
            self.send_response(404)
            self.end_headers()
            return

        cpu = random.randint(5, 99)

        if random.random() < 0.08:
            cpu = random.randint(100, 127)

        ram = random.randint(8, 97)

        if random.random() < 0.05:
            ram = random.randint(98, 101)

        storage = random.randint(15, 97)

        if random.random() < 0.04:
            storage = random.randint(98, 100)

        temperature = random.randint(35, 89)

        if random.random() < 0.08:
            temperature = random.randint(90, 140)

        data = {
            "host_info_is_available": True,
            "boot_time": start_time,
            "hostname": "GASPAR-3",
            "platform": "Android",
            "cpu": {
                "load_is_available": True,
                "load1_percent": cpu,
                "load15_percent": random.randint(5, 100),
                "temperature_is_available": True,
                "temperature_c": temperature
            },
            "memory": {
                "memory_is_available": True,
                "total_mb": 8192,
                "used_mb": int(8192 * ram / 100),
                "used_percent": ram,
                "swap_is_available": True,
                "swap_total_mb": 4096,
                "swap_used_mb": random.randint(0, 4096),
                "swap_used_percent": random.randint(0, 100)
            },
            "mountpoints": [
                {
                    "path": "/storage/emulated/0",
                    "name": "Internal Storage",
                    "total_mb": 128000,
                    "used_mb": int(128000 * storage / 100),
                    "used_percent": storage
                }
            ]
        }

        body = json.dumps(data).encode()

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


server = HTTPServer((HOST, PORT), Handler)

print(f"GASPAR-3 fake agent listening on http://{HOST}:{PORT}")

server.serve_forever()
