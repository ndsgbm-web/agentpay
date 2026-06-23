"""Smoke-test the AgentPay API: start it, browse, claim, submit."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_DIR = ROOT / "api"
PORT = 18765


def wait_for_port(port, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), 0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def http_json(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def main():
    data_dir = ROOT / ".agentpay-data"
    if data_dir.exists():
        for p in data_dir.glob("*"):
            p.unlink()

    print("Starting API on port", PORT)
    env = {**os.environ, "AGENTPAY_DATA": str(data_dir), "AGENTPAY_PORT": str(PORT)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--port", str(PORT), "--log-level", "warning"],
        cwd=str(API_DIR), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        if not wait_for_port(PORT):
            out, _ = proc.communicate(timeout=2)
            print("API failed to start:")
            print(out.decode()[:2000])
            return 1

        print("\n[1] POST /tasks/ingest  (simulate runx scraper)")
        result = http_json("POST", f"http://127.0.0.1:{PORT}/tasks/ingest", {
            "source": "runx",
            "external_id": "test-1",
            "title": "Translate 1000 words ZH->EN",
            "description": "Translate the provided article from Simplified Chinese to English. Preserve technical terms. Return as a markdown file.",
            "category": "translation",
            "budget_usdc": 10.0,
            "deadline_hours": 48,
            "required_stake": 2.0,
            "url": "https://example.com/article",
            "buyer_address": "0x27fe5055144366ec371e0231aa2d7b5f6042b839",
        })
        task_id = result["id"]
        task = http_json("GET", f"http://127.0.0.1:{PORT}/tasks/{task_id}")
        print(f"   task id: {task_id}")
        print(f"   title:   {task['title']}")
        print(f"   budget:  {task['budget_usdc']} USDC  stake: {task['required_stake']} USDC")

        print("\n[2] GET /tasks?status=open&source=runx")
        out = http_json("GET", f"http://127.0.0.1:{PORT}/tasks?status=open&source=runx")
        print(f"   open runx tasks: {len(out.get('tasks', []))}")
        assert len(out["tasks"]) >= 1

        print("\n[3] POST /tasks/{id}/claim")
        seller_addr = "0x6813Eb9362372EEF6200f3b1dbC3f819671cBA69"
        out = http_json("POST", f"http://127.0.0.1:{PORT}/tasks/{task_id}/claim",
                        {"seller_address": seller_addr})
        print(f"   status: {out.get('status')}")
        assert out["status"] == "claimed"

        print("\n[4] POST /tasks/{id}/submit")
        out = http_json("POST", f"http://127.0.0.1:{PORT}/tasks/{task_id}/submit",
                        {"seller_address": seller_addr,
                         "proof": "Translation complete: see https://example.com/result.md"})
        print(f"   status: {out.get('status')}")
        assert out["status"] == "submitted"

        print("\n[5] POST /tasks/{id}/settle  (query params)")
        escrow_id_hex = "0x" + "42" * 32
        tx_hash_hex = "0x" + "ab" * 32
        out = http_json("POST",
            f"http://127.0.0.1:{PORT}/tasks/{task_id}/settle?escrow_id={escrow_id_hex}&tx_hash={tx_hash_hex}")
        print(f"   status: {out.get('status')}")
        assert out["status"] == "settled"

        print("\n[6] GET /stats")
        out = http_json("GET", f"http://127.0.0.1:{PORT}/stats")
        print(f"   {out}")

        print("\n\033[32m=== API SMOKE TEST PASSED ===\033[0m")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
