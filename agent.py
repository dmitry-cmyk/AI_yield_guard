"""
Yield Guardian Agent - Core Module

Monitors your wallet on Base chain and enforces "spend from yield only" rules.
Supports real DeFi yield tracking from Aave V3.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum

import yaml
import aiohttp
import aiosqlite
from rich.console import Console

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('yield_guardian')
console = Console()


# ═══════════════════════════════════════════════════════════════════
# BASE CHAIN CONFIGURATION
# ═══════════════════════════════════════════════════════════════════

BASE_CHAIN_CONFIG = {
    "chain_id": 8453,
    "rpc_url": "https://mainnet.base.org",
    "explorer_api": "https://api.basescan.org/api",
    "explorer_url": "https://basescan.org",
    
    # Stablecoin addresses on Base
    "tokens": {
        "USDC": {
            "address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "decimals": 6
        },
        "USDbC": {
            "address": "0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6CA",
            "decimals": 6
        },
        "DAI": {
            "address": "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",
            "decimals": 18
        },
    },
    
    # DeFi Protocol Addresses on Base
    "aave_v3": {
        "pool": "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5",
        "aUSDC": "0x4e65fE4DbA92790696d040ac24Aa414708F5c0AB",
    },
}


class SpendingMode(Enum):
    CONSERVATIVE = 0.5
    BALANCED = 0.8
    GROWTH = 0.3


@dataclass
class YieldSource:
    name: str
    source_type: str
    principal_usd: Decimal
    apy_percent: Decimal
    last_updated: datetime = field(default_factory=datetime.now)
    protocol_address: Optional[str] = None
    
    @property
    def daily_yield(self) -> Decimal:
        return (self.principal_usd * (self.apy_percent / 100)) / 365
    
    @property
    def hourly_yield(self) -> Decimal:
        return self.daily_yield / 24


@dataclass 
class Transaction:
    tx_hash: str
    timestamp: datetime
    amount_usd: Decimal
    token: str
    direction: str
    merchant: Optional[str] = None
    category: Optional[str] = None
    status: str = 'detected'


@dataclass
class AgentState:
    principal_usd: Decimal
    accrued_yield_usd: Decimal
    spent_from_yield_usd: Decimal
    spending_mode: SpendingMode
    yield_sources: list
    last_yield_update: datetime
    transactions: list = field(default_factory=list)
    
    @property
    def available_budget(self) -> Decimal:
        net_yield = self.accrued_yield_usd - self.spent_from_yield_usd
        return net_yield * Decimal(str(self.spending_mode.value))
    
    @property
    def total_daily_yield(self) -> Decimal:
        return sum(s.daily_yield for s in self.yield_sources)
    
    def add_yield(self, hours: float = 1) -> Decimal:
        total_hourly = sum(s.hourly_yield for s in self.yield_sources)
        accrued = total_hourly * Decimal(str(hours))
        self.accrued_yield_usd += accrued
        self.last_yield_update = datetime.now()
        return accrued
    
    def record_spending(self, amount_usd: Decimal) -> tuple:
        net_yield = self.accrued_yield_usd - self.spent_from_yield_usd
        budget = net_yield * Decimal(str(self.spending_mode.value))
        
        if amount_usd <= budget:
            self.spent_from_yield_usd += amount_usd
            return True, f"✅ Spent ${amount_usd:.2f} from yield (${budget - amount_usd:.2f} remaining)"
        else:
            self.spent_from_yield_usd += amount_usd
            overage = amount_usd - budget
            return False, f"⚠️ Over budget by ${overage:.2f}! This dips into principal."


class BaseChainMonitor:
    """Monitors wallet activity on Base chain via RPC"""
    
    def __init__(self, wallet_address: str, api_key: str = ""):
        self.wallet_address = wallet_address.lower()
        self.rpc_url = BASE_CHAIN_CONFIG["rpc_url"]
        self.api_key = api_key
        self._session: Optional[aiohttp.ClientSession] = None
        self.seen_tx_hashes: set = set()
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def _call_rpc(self, method: str, params: list) -> dict:
        session = await self._get_session()
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        try:
            async with session.post(self.rpc_url, json=payload) as response:
                return await response.json()
        except Exception as e:
            logger.error(f"RPC call failed: {e}")
            return {}
    
    async def get_token_balance(self, token_address: str, decimals: int = 18) -> Decimal:
        """Get ERC20 token balance via RPC"""
        padded_address = self.wallet_address[2:].zfill(64)
        call_data = f"0x70a08231{padded_address}"
        
        result = await self._call_rpc("eth_call", [
            {"to": token_address, "data": call_data},
            "latest"
        ])
        
        if "result" in result and result["result"] != "0x":
            try:
                balance_raw = int(result["result"], 16)
                return Decimal(balance_raw) / Decimal(10**decimals)
            except (ValueError, TypeError):
                pass
        return Decimal(0)
    
    async def get_stablecoin_balances(self) -> dict:
        balances = {}
        for symbol, info in BASE_CHAIN_CONFIG["tokens"].items():
            balance = await self.get_token_balance(info["address"], info["decimals"])
            if balance > 0:
                balances[symbol] = balance
        return balances
    
    async def get_total_balance_usd(self) -> Decimal:
        balances = await self.get_stablecoin_balances()
        return sum(balances.values()) if balances else Decimal(0)
    
    async def get_new_outgoing_transfers(self) -> list:
        # Simplified - in production, use event logs or indexer
        return []


class DeFiYieldTracker:
    """Tracks yield from DeFi protocols"""
    
    def __init__(self, wallet_address: str, rpc_url: str = None):
        self.wallet_address = wallet_address.lower()
        self.rpc_url = rpc_url or BASE_CHAIN_CONFIG["rpc_url"]
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def _call_rpc(self, method: str, params: list) -> dict:
        session = await self._get_session()
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        try:
            async with session.post(self.rpc_url, json=payload) as response:
                return await response.json()
        except Exception as e:
            logger.error(f"RPC call failed: {e}")
            return {}
    
    async def get_aave_usdc_balance(self) -> tuple:
        """Get Aave aUSDC balance and estimated APY"""
        atoken_address = BASE_CHAIN_CONFIG["aave_v3"]["aUSDC"]
        padded_address = self.wallet_address[2:].zfill(64)
        data = f"0x70a08231{padded_address}"
        
        result = await self._call_rpc("eth_call", [
            {"to": atoken_address, "data": data},
            "latest"
        ])
        
        balance = Decimal(0)
        if "result" in result and result["result"] != "0x":
            try:
                balance_raw = int(result["result"], 16)
                balance = Decimal(balance_raw) / Decimal(10**6)
            except (ValueError, TypeError):
                pass
        
        # Estimated APY - in production, fetch from Aave contracts
        apy = Decimal("4.0")
        return balance, apy
    
    async def get_all_yield_sources(self) -> list:
        sources = []
        aave_balance, aave_apy = await self.get_aave_usdc_balance()
        
        if aave_balance > 0:
            sources.append(YieldSource(
                name="Aave V3 USDC",
                source_type="aave_v3",
                principal_usd=aave_balance,
                apy_percent=aave_apy,
                protocol_address=BASE_CHAIN_CONFIG["aave_v3"]["pool"]
            ))
        return sources


class YieldGuardianAgent:
    """Main agent that orchestrates yield tracking and spending rules"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        self.state = self._init_state()
        
        # Use safe_address if available, else wallet_address
        wallet = self.config.get('safe_address') or self.config.get('wallet_address')
        self.monitor = BaseChainMonitor(
            wallet_address=wallet,
            api_key=self.config.get('basescan_api_key', '')
        )
        self.yield_tracker = DeFiYieldTracker(wallet_address=wallet)
        self.db_path = self.config.get('database_path', 'data/transactions.db')
        self._running = False
    
    def _load_config(self, config_path: str) -> dict:
        try:
            with open(config_path, 'r') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            logger.error(f"Config file not found: {config_path}")
            raise
    
    def _init_state(self) -> AgentState:
        config = self.config
        mode_str = config.get('spending_mode', 'balanced').upper()
        spending_mode = SpendingMode[mode_str]
        
        yield_sources = []
        for source_config in config.get('yield_sources', []):
            yield_sources.append(YieldSource(
                name=source_config.get('name', 'Unknown'),
                source_type=source_config.get('type', 'simulated'),
                principal_usd=Decimal(str(source_config.get('principal_usd', 0))),
                apy_percent=Decimal(str(source_config.get('apy_percent', 0))),
                protocol_address=source_config.get('protocol_address')
            ))
        
        return AgentState(
            principal_usd=Decimal(str(config.get('principal_usd', 0))),
            accrued_yield_usd=Decimal(str(config.get('initial_yield', 0))),
            spent_from_yield_usd=Decimal('0'),
            spending_mode=spending_mode,
            yield_sources=yield_sources,
            last_yield_update=datetime.now()
        )
    
    async def init_database(self):
        import os
        os.makedirs(os.path.dirname(self.db_path) if os.path.dirname(self.db_path) else '.', exist_ok=True)
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS transactions (
                    tx_hash TEXT PRIMARY KEY,
                    timestamp DATETIME,
                    amount_usd REAL,
                    token TEXT,
                    direction TEXT,
                    merchant TEXT,
                    category TEXT,
                    status TEXT,
                    within_budget INTEGER
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS state_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME,
                    principal_usd REAL,
                    accrued_yield_usd REAL,
                    spent_from_yield_usd REAL,
                    spending_mode TEXT
                )
            ''')
            await db.commit()
    
    async def save_transaction(self, tx: Transaction, within_budget: bool):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                INSERT OR REPLACE INTO transactions 
                (tx_hash, timestamp, amount_usd, token, direction, merchant, category, status, within_budget)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                tx.tx_hash, tx.timestamp.isoformat(), float(tx.amount_usd),
                tx.token, tx.direction, tx.merchant, tx.category, tx.status,
                1 if within_budget else 0
            ))
            await db.commit()
    
    async def save_state_snapshot(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                INSERT INTO state_snapshots 
                (timestamp, principal_usd, accrued_yield_usd, spent_from_yield_usd, spending_mode)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                datetime.now().isoformat(),
                float(self.state.principal_usd),
                float(self.state.accrued_yield_usd),
                float(self.state.spent_from_yield_usd),
                self.state.spending_mode.name
            ))
            await db.commit()
    
    async def update_yield(self):
        hours_since = (datetime.now() - self.state.last_yield_update).total_seconds() / 3600
        if hours_since >= 0.1:
            self.state.add_yield(hours_since)
    
    async def update_yield_from_defi(self):
        try:
            defi_sources = await self.yield_tracker.get_all_yield_sources()
            if defi_sources:
                simulated = [s for s in self.state.yield_sources if s.source_type == 'simulated']
                self.state.yield_sources = simulated + defi_sources
                logger.info(f"Updated {len(defi_sources)} DeFi yield sources")
        except Exception as e:
            logger.warning(f"Could not update DeFi yields: {e}")
    
    async def process_new_transactions(self) -> list:
        results = []
        new_transfers = await self.monitor.get_new_outgoing_transfers()
        
        for tx in new_transfers:
            if tx.amount_usd > 0:
                is_within_budget, message = self.state.record_spending(tx.amount_usd)
                tx.status = 'within_budget' if is_within_budget else 'over_budget'
                await self.save_transaction(tx, is_within_budget)
                results.append((tx, is_within_budget, message))
                logger.info(f"Transaction {tx.tx_hash[:8]}...: ${tx.amount_usd:.2f} - {message}")
        
        return results
    
    async def get_status(self) -> dict:
        balances = await self.monitor.get_stablecoin_balances()
        return {
            "wallet": self.config.get('safe_address', self.config.get('wallet_address', ''))[:8] + "...",
            "chain": "Base",
            "balances": {k: float(v) for k, v in balances.items()},
            "total_balance_usd": float(sum(balances.values())) if balances else 0,
            "principal_usd": float(self.state.principal_usd),
            "accrued_yield_usd": float(self.state.accrued_yield_usd),
            "spent_from_yield_usd": float(self.state.spent_from_yield_usd),
            "available_budget": float(self.state.available_budget),
            "spending_mode": self.state.spending_mode.name,
            "daily_yield_usd": float(self.state.total_daily_yield),
            "yield_sources": [
                {
                    "name": s.name,
                    "type": s.source_type,
                    "principal": float(s.principal_usd),
                    "apy": float(s.apy_percent),
                    "daily_yield": float(s.daily_yield)
                }
                for s in self.state.yield_sources
            ]
        }
    
    def get_status_summary(self) -> str:
        s = self.state
        return f"""🛡️ *Yield Guardian Status*

💰 *Principal Protected:* ${s.principal_usd:,.2f}
📈 *Yield Accrued:* ${s.accrued_yield_usd:,.2f}
💸 *Yield Spent:* ${s.spent_from_yield_usd:,.2f}
✅ *Available Budget:* ${s.available_budget:,.2f}

⚙️ *Mode:* {s.spending_mode.name.title()} ({int(s.spending_mode.value * 100)}%)
📊 *Daily Yield:* ${s.total_daily_yield:,.2f}/day"""
    
    def get_budget_details(self) -> str:
        s = self.state
        net_yield = s.accrued_yield_usd - s.spent_from_yield_usd
        
        return f"""📊 *Budget Details*

*Yield Account:*
  Accrued: ${s.accrued_yield_usd:,.2f}
  Spent: ${s.spent_from_yield_usd:,.2f}
  Net: ${net_yield:,.2f}

*Spending Budget:*
  Mode: {s.spending_mode.name} ({int(s.spending_mode.value * 100)}%)
  Available: ${s.available_budget:,.2f}
  Reserved: ${net_yield - s.available_budget:,.2f}

*Projections:*
  Daily yield: ${s.total_daily_yield:,.2f}
  Weekly: ${s.total_daily_yield * 7:,.2f}
  Monthly: ${s.total_daily_yield * 30:,.2f}"""
    
    def stop(self):
        self._running = False


def get_explorer_url(tx_hash: str) -> str:
    return f"{BASE_CHAIN_CONFIG['explorer_url']}/tx/{tx_hash}"
