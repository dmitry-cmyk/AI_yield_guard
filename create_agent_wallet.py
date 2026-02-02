#!/usr/bin/env python3
"""
Generate a new wallet for the Yield Guardian agent.
This wallet will have limited permissions via Safe spending limits.
"""

from eth_account import Account

def main():
    account = Account.create()
    
    print("=" * 60)
    print("🤖 YIELD GUARDIAN AGENT WALLET")
    print("=" * 60)
    print()
    print(f"📍 Address:     {account.address}")
    print(f"🔑 Private Key: {account.key.hex()}")
    print()
    print("=" * 60)
    print("⚠️  IMPORTANT:")
    print("1. Save the private key securely")
    print("2. Add the ADDRESS to your Safe spending limit")
    print("3. Add the PRIVATE KEY to your config.yaml")
    print("4. Never share or commit the private key")
    print("=" * 60)

if __name__ == "__main__":
    main()
