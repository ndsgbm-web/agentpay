"""Smoke-test the AgentPay API: deposit/claim/submit/settle/stake-gate."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
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


def http_raw(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        try:
            body = json.loads(body)
        except Exception:
            pass
        return e.code, body


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
        status, result = http_raw("POST", f"http://127.0.0.1:{PORT}/tasks/ingest", {
            "source": "runx",
            "external_id": "test-1",
            "title": "Translate 1000 words ZH->EN",
            "description": "Translate the provided article from Simplified Chinese to English.",
            "category": "translation",
            "budget_usdc": 10.0,
            "deadline_hours": 48,
            "required_stake": 2.0,
            "url": "https://example.com/article",
            "buyer_address": "0x27fe5055144366ec371e0231aa2d7b5f6042b839",
        })
        assert status == 200, (status, result)
        task_id = result["id"]
        task_resp, _ = http_raw("GET", f"http://127.0.0.1:{PORT}/tasks/{task_id}")
        assert task_resp == 200
        print(f"   task id: {task_id}  budget: 10.0 USDC  stake: 2.0 USDC")

        print("\n[2] GET /tasks?status=open&source=runx")
        s, out = http_raw("GET", f"http://127.0.0.1:{PORT}/tasks?status=open&source=runx")
        print(f"   open runx tasks: {len(out.get('tasks', []))}")
        assert s == 200 and len(out["tasks"]) >= 1

        seller_addr = "0x6813Eb9362372EEF6200f3b1dbC3f819671cBA69"

        print("\n[3] POST /tasks/{id}/claim  (NO deposit — should 402)")
        s, body = http_raw("POST", f"http://127.0.0.1:{PORT}/tasks/{task_id}/claim",
                           {"seller_address": seller_addr})
        print(f"   status={s}  body={body}")
        assert s == 402, f"expected 402 stake-gate, got {s}"

        print("\n[4] POST /agents/{addr}/stake  (deposit 2 USDC, off-chain bookkeeping)")
        s, body = http_raw("POST", f"http://127.0.0.1:{PORT}/agents/{seller_addr}/stake",
                           {"amount_usdc": 2.0, "task_id": "", "tx_hash": ""})
        print(f"   status={s}  body={body}")
        assert s == 200

        print("\n[5] POST /tasks/{id}/claim  (with deposit — should succeed)")
        s, body = http_raw("POST", f"http://127.0.0.1:{PORT}/tasks/{task_id}/claim",
                           {"seller_address": seller_addr})
        print(f"   status: {body.get('status')}")
        assert s == 200 and body["status"] == "claimed"

        print("\n[6] POST /tasks/{id}/submit")
        s, body = http_raw("POST", f"http://127.0.0.1:{PORT}/tasks/{task_id}/submit",
                           {"seller_address": seller_addr,
                            "proof": "Translation complete: see https://example.com/result.md"})
        print(f"   status: {body.get('status')}")
        assert s == 200 and body["status"] == "submitted"

        print("\n[7] POST /tasks/{id}/settle  (query params)")
        escrow_id_hex = "0x" + "42" * 32
        tx_hash_hex = "0x" + "ab" * 32
        s, body = http_raw("POST",
            f"http://127.0.0.1:{PORT}/tasks/{task_id}/settle?escrow_id={escrow_id_hex}&tx_hash={tx_hash_hex}")
        print(f"   status: {body.get('status')}")
        assert s == 200 and body["status"] == "settled"

        print("\n[8] GET /stats")
        s, out = http_raw("GET", f"http://127.0.0.1:{PORT}/stats")
        print(f"   tasks_by_source: {out.get('tasks_by_source')}")
        assert s == 200

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
