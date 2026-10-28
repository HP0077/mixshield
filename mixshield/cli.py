"""Command line: `mixshield proxy --upstream "<command that starts an MCP server>"`."""

import argparse
import asyncio
import os


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mixshield")
    commands = parser.add_subparsers(dest="command", required=True)
    proxy = commands.add_parser("proxy", help="MCP proxy: gate every tool call, screen every tool output")
    proxy.add_argument("--upstream", required=True, help="command that starts the MCP server (stdio)")
    proxy.add_argument("--config", help='JSON file: {"policy": {tool: {arg: kind}}, "trusted": [values], '
                                        '"low_risk": [tool names]}')
    proxy.add_argument("--user-task", default=os.environ.get("MIXSHIELD_USER_TASK", ""),
                       help="the user's own request; values written in it are trusted (default: env MIXSHIELD_USER_TASK)")
    proxy.add_argument("--screen", choices=["mixshield", "stub"], default="mixshield",
                       help="mixshield = the real screen (Prompt Guard 2 + Muse Spark Open, fails closed); "
                            "stub = flag only outputs containing a --stub-flag text (for tests)")
    proxy.add_argument("--stub-flag", action="append", default=[],
                       help="with --screen stub: flag any tool output containing this text (repeat for more)")
    proxy.add_argument("--approver", choices=["none", "rule"], default="none",
                       help="who answers an 'ask': none = the call is not run and the client is told to ask the user; "
                            "rule = the rule-based approver (for experiments)")
    args = parser.parse_args(argv)
    if args.stub_flag and args.screen != "stub":
        parser.error("--stub-flag needs --screen stub")

    from mixshield.proxy import serve  # imported here so other commands do not need the mcp package

    asyncio.run(serve(args.upstream, args.config, args.user_task, args.stub_flag, args.approver, args.screen))


if __name__ == "__main__":
    main()
