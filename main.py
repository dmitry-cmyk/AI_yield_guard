#!/usr/bin/env python3
"""
Yield Guardian Agent - Main Entry Point

An AI agent that enforces "spend only from yield" rules
using self-custody wallets and smart contracts.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from agent import YieldGuardianAgent
from telegram_bot import TelegramBot

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('yield_guardian')


async def main():
    # Initialize agent
    agent = YieldGuardianAgent("config.yaml")
    bot = TelegramBot(agent)
    
    # Setup database
    await agent.init_database()
    
    # Start Telegram bot
    await bot.start()
    
    logger.info(f"Yield Guardian started")
    logger.info(f"Monitoring wallet: {agent.config.get('safe_address', agent.config.get('wallet_address', 'N/A'))}")
    logger.info("Press Ctrl+C to stop")
    
    # Tracking for periodic updates
    last_yield_update = datetime.now()
    last_defi_update = datetime.now() - timedelta(hours=1)
    
    try:
        while True:
            # Update DeFi yields every hour
            if (datetime.now() - last_defi_update).total_seconds() > 3600:
                await agent.update_yield_from_defi()
                last_defi_update = datetime.now()
            
            # Accrue yield continuously
            await agent.update_yield()
            
            # Save state snapshot every hour
            hours_since = (datetime.now() - last_yield_update).total_seconds() / 3600
            if hours_since >= 1:
                await agent.save_state_snapshot()
                last_yield_update = datetime.now()
            
            # Check for new transactions
            results = await agent.process_new_transactions()
            for tx, is_within_budget, message in results:
                await bot.send_transaction_alert(tx, is_within_budget, message)
            
            # Sleep between checks
            await asyncio.sleep(30)
    
    except asyncio.CancelledError:
        pass
    finally:
        await bot.stop()
        await agent.monitor.close()
        await agent.yield_tracker.close()
        logger.info("Yield Guardian stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down...")
