"""The local MCP adapter between Claude and this machine.

Deliberately thin: `validate.py` gates every argument against an allowlist,
`jobs.py` runs long work as identified one-at-a-time processes, and
`server.py` exposes the tools. No module here can place an exchange order.
"""
