"""
Transfer Executor - Executes USDC transfers from agent wallet to Wirex Pay
Uses the agent's limited wallet (funded via Safe spending limits)
"""

import os
import asyncio
import logging
from decimal import Decimal
from web3 import Web3
from eth_account import Account

logger = logging.getLogger('yield_guardian.executor')

# Base chain config
BASE_RPC = "https://mainnet.base.org"
USDC_ADDRESS = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
USDC_DECIMALS = 6

# ERC20 ABI (minimal - just what we need)
ERC20_ABI = [
    {
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "amount", "type": "uint256"}
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    }
]


class TransferExecutor:
    """
    Handles automatic USDC transfers from agent wallet to Wirex Pay.
    
    The agent wallet is funded via Safe spending limits, ensuring
    it can only access yield, never principal.
    """
    
    def __init__(self, config: dict):
        self.config = config
        self.w3 = Web3(Web3.HTTPProvider(BASE_RPC))
        
        # Load agent wallet - prefer environment variable for security
        private_key = os.environ.get('AGENT_PRIVATE_KEY') or config.get('agent_private_key', '')
        if not private_key:
            raise ValueError("AGENT_PRIVATE_KEY environment variable required")
        if not private_key.startswith('0x'):
            private_key = '0x' + private_key
        self.agent_account = Account.from_key(private_key)
        
        # Destination
        self.wirex_pay_address = config.get('wirex_pay_address', '')
        
        # USDC contract
        self.usdc_contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(USDC_ADDRESS),
            abi=ERC20_ABI
        )
    
    def get_agent_usdc_balance(self) -> Decimal:
        """Check USDC balance of agent wallet"""
        balance = self.usdc_contract.functions.balanceOf(
            self.agent_account.address
        ).call()
        return Decimal(balance) / Decimal(10 ** USDC_DECIMALS)
    
    def get_agent_eth_balance(self) -> Decimal:
        """Check ETH balance for gas"""
        balance = self.w3.eth.get_balance(self.agent_account.address)
        return Decimal(balance) / Decimal(10 ** 18)
    
    async def transfer_to_wirex(self, amount_usd: float) -> dict:
        """
        Transfer USDC from agent wallet to Wirex Pay.
        
        Returns:
            dict with 'success', 'tx_hash', 'amount', 'explorer_url' or 'error'
        """
        
        # Check balances
        usdc_balance = self.get_agent_usdc_balance()
        eth_balance = self.get_agent_eth_balance()
        
        if usdc_balance < Decimal(str(amount_usd)):
            return {
                "success": False,
                "error": f"Insufficient USDC. Have ${usdc_balance:.2f}, need ${amount_usd:.2f}"
            }
        
        if eth_balance < Decimal("0.0001"):
            return {
                "success": False,
                "error": f"Insufficient ETH for gas. Have {eth_balance:.6f} ETH"
            }
        
        try:
            # Build transaction
            amount_raw = int(Decimal(str(amount_usd)) * Decimal(10 ** USDC_DECIMALS))
            
            tx = self.usdc_contract.functions.transfer(
                Web3.to_checksum_address(self.wirex_pay_address),
                amount_raw
            ).build_transaction({
                'from': self.agent_account.address,
                'nonce': self.w3.eth.get_transaction_count(self.agent_account.address),
                'gas': 100000,
                'gasPrice': self.w3.eth.gas_price,
                'chainId': 8453  # Base
            })
            
            # Sign and send
            signed_tx = self.w3.eth.account.sign_transaction(tx, self.agent_account.key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            
            # Wait for confirmation
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt['status'] == 1:
                logger.info(f"Transfer successful: ${amount_usd} USDC to Wirex Pay")
                return {
                    "success": True,
                    "tx_hash": tx_hash.hex(),
                    "amount": amount_usd,
                    "explorer_url": f"https://basescan.org/tx/{tx_hash.hex()}"
                }
            else:
                return {
                    "success": False,
                    "error": "Transaction failed on-chain"
                }
                
        except Exception as e:
            logger.error(f"Transfer failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_status(self) -> dict:
        """Get current status of agent wallet"""
        return {
            "agent_address": self.agent_account.address,
            "usdc_balance": float(self.get_agent_usdc_balance()),
            "eth_balance": float(self.get_agent_eth_balance()),
            "wirex_destination": self.wirex_pay_address
        }
