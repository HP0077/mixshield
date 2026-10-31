# Clip 2: a different MCP client (MCP Inspector) through the same proxy

Goal (about 15 s on video): a client that is not our agent, with one config change, gets the same protection.
The two config files differ only in the server command:

```diff
--- demo/inspector/direct.json
+++ demo/inspector/mixshield.json
-      "command": "python",
-      "args": ["-X", "utf8", "-m", "demo.mcp_server"]
+      "command": "mixshield",
+      "args": ["proxy", "--upstream", "python -X utf8 -m demo.mcp_server", "--config", "demo/policy.json", "--user-task", "Pay invoice INV-102"],
+      "connectionTimeout": 120000
```

(The proxy starts the demo server itself, so "the config change" is: put `mixshield proxy --upstream "<the old command>"` in front of it. `connectionTimeout` is explained below.)

## Run it (PowerShell, repo root)

```powershell
.\.venv\Scripts\Activate.ps1                      # so that "mixshield" and "python" are the venv's
# Before recording: start the proxy once so the OS file cache is warm (see "Start-up time").
npx -y @modelcontextprotocol/inspector@2.12.0 --web --config demo/inspector/mixshield.json --server invoices --cwd .
```

The pinned version is **2.12.0** (released 21 Oct 2026; 2.13.0 came out 28 Oct and was not tested). For the "before" shot use `demo/inspector/direct.json` the same way. Inspector opens the browser itself.

Steps in the Inspector window (Connect, then the Tools tab):
1. `read_email` with `email_id` = 3. The output ends with the MixShield notice if the screen flagged the email.
2. `transfer_money` with `iban` = `ZZ00DEMO0000000099`, `amount` = 480, `reference` = `INV-102`. Expected: the result says **MixShield BLOCKED the call... It was NOT run.**
3. `transfer_money` with `iban` = `ZZ00DEMO0000000002`, `amount` = 480, `reference` = `INV-102`. Expected: `"status": "sent"` (a saved payee).

If the screen does not flag the email in step 1 (it happened in 1 of 6 real runs, see `docs/demo_log.md`), step 2 says "MixShield needs the user's confirmation... It was NOT run." instead. Show it as it is; do not retake until it flags. Money does not move in either case.

Watch out: the proxy keeps the "this email was flagged" memory for one session. Calls must be made in the same connection (do not disconnect between step 1 and step 2). Inspector's `--cli` mode starts a new process per call, so it cannot show the block; use the web window.

## Start-up time and the timeout (checked 31 Oct)

The proxy loads Prompt Guard 2 before it answers the client. Measured on this machine (CPU only), time until the proxy answers `initialize`: **38.5 s, 30.9 s, 18.1 s** (three runs in a row, falling as the disk cache warms), later runs 15.5 s and 21.4 s.

Inspector's default connection timeout is **30 s** (read in its source, `DEFAULT_CONNECTION_TIMEOUT_MS`; its default request timeout is the SDK's 60 s). With the default, the first test through the proxy failed: `Connection timed out after 30000 ms`. The fix is `"connectionTimeout": 120000` on the server entry in the config file (Inspector reads it per server). With it, `tools/list` through the proxy worked (21.4 s). The proxy also prints `mixshield: loading Prompt Guard 2 ...` to stderr, so the Inspector's log pane shows why it waits.
Other clients have their own timeouts. A client with a fixed connect limit under about 40 s can fail on a cold start; this is the cost of loading the model in the proxy before it serves.

## What was and was not verified

- Verified: Inspector 2.12.0 `--cli` connects through the proxy with this config and lists the 4 tools (21.4 s). With the default 30 s timeout it failed (35.7 s run), as described above.
- Verified: the three steps above in one session, using a Python MCP client that starts the server from the same config file (`python -X utf8 -m demo.inspector_check demo/inspector/mixshield.json`): step 1 flagged, step 2 blocked, step 3 sent. With `direct.json` both payments go through.
- **Not verified: clicking through the Inspector web window.** I could not drive a browser window. Do one dry run of the three steps before recording.
