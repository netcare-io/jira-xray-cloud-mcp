# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

from xray_mcp.server import create_server

# Configured from XRAY_* environment variables, see xray_mcp/config.py.
mcp = create_server()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
