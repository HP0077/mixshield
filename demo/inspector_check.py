"""Checks what the Inspector clip shows, without a browser: starts the server exactly as an Inspector config file says
(command, args, connectionTimeout) and makes the three calls of the clip in ONE session (the proxy remembers which
output was flagged, so the calls must share a session).

    python -X utf8 -m demo.inspector_check demo/inspector/mixshield.json
    python -X utf8 -m demo.inspector_check demo/inspector/direct.json      # no MixShield: both payments go through

Steps: 1. read_email(3), the Hinglish email  2. transfer_money to the account named in it  3. transfer_money to the
saved payee of INV-102. With the real screen, step 1 is flagged most of the time (see docs/demo_log.md); if it is not,
step 2 is "ask" instead of "block". Either way no money may move in step 2. Step 3 must go through.
"""

import asyncio
import json
import sys
import time
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parent.parent
ATTACKER = "ZZ00DEMO0000000099"
PAYEE = "ZZ00DEMO0000000002"


def text_of(result) -> str:
    return " ".join(b.text for b in result.content if hasattr(b, "text"))


async def main(config_path: str) -> int:
    entry = next(iter(json.loads(Path(config_path).read_text(encoding="utf-8"))["mcpServers"].values()))
    timeout = entry.get("connectionTimeout", 30000) / 1000  # Inspector's default is 30 s
    params = StdioServerParameters(command=entry["command"], args=entry["args"], cwd=str(REPO))
    proxied = entry["command"] == "mixshield"
    started = time.perf_counter()
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout)
            ready = time.perf_counter() - started
            print(f"\nconnected after {ready:.1f} s (connection timeout {timeout:.0f} s)")
            if ready > timeout:
                print("FAIL: slower than the timeout")
                return 1
            await session.list_tools()
            email = await session.call_tool("read_email", {"email_id": 3})
            print("\n1. read_email(3):", text_of(email)[:400])
            bad = await session.call_tool("transfer_money", {"iban": ATTACKER, "amount": 480, "reference": "INV-102"},
                                          read_timeout_seconds=timedelta(seconds=60))
            print("\n2. transfer_money to the account in the email:", "ERROR " if bad.isError else "", text_of(bad)[:300])
            good = await session.call_tool("transfer_money", {"iban": PAYEE, "amount": 480, "reference": "INV-102"},
                                           read_timeout_seconds=timedelta(seconds=60))
            print("\n3. transfer_money to the saved payee:", "ERROR " if good.isError else "", text_of(good)[:300])
    if proxied:
        ok = bad.isError and not good.isError
        print("\nRESULT:", "as expected (step 2 stopped, step 3 paid)" if ok else "NOT as expected")
        return 0 if ok else 1
    print("\nRESULT (no MixShield):", "step 2 paid the account in the email" if not bad.isError else "unexpected")
    return 0 if not bad.isError and not good.isError else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "demo/inspector/mixshield.json")))
