"""
Yield Guardian Agent - Telegram Bot Interface
"""

import asyncio
import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes
)
from telegram.constants import ParseMode

from agent import YieldGuardianAgent, Transaction, SpendingMode
from transfer_executor import TransferExecutor

logger = logging.getLogger('yield_guardian.telegram')


class TelegramBot:
    def __init__(self, agent: YieldGuardianAgent):
        self.agent = agent
        self.config = agent.config
        tg_config = self.config.get('telegram', {})
        self.token = tg_config.get('bot_token') or self.config.get('telegram_token', '')
        self.authorized_user_id = tg_config.get('authorized_user_id') or self.config.get('telegram_user_id', 0)
        self.app: Optional[Application] = None
        self._executor: Optional[TransferExecutor] = None
    
    def _get_executor(self) -> TransferExecutor:
        if self._executor is None:
            self._executor = TransferExecutor(self.config)
        return self._executor
    
    def _is_authorized(self, user_id: int) -> bool:
        return user_id == self.authorized_user_id
    
    async def _check_auth(self, update: Update) -> bool:
        if not self._is_authorized(update.effective_user.id):
            await update.message.reply_text("⛔ Unauthorized.")
            return False
        return True
    
    # ═══════════════════════════════════════════════════════════════
    # CORE COMMANDS
    # ═══════════════════════════════════════════════════════════════
    
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        
        welcome = """🛡️ *Yield Guardian Active!*

I'm protecting your principal and managing your spending budget.

*💰 Spending:*
/spend <amount> - Check if amount is within budget
/topup - See available yield for card
/transfer <amount> - Send yield to Wirex card

*📊 Status:*
/status - Overview of balances & budget
/budget - Detailed budget breakdown
/yield - Yield accrual details

*⚙️ Settings:*
/mode - Change spending mode
/agent - Agent wallet status
/help - All commands

_Your principal is always protected._"""
        
        await update.message.reply_text(welcome, parse_mode=ParseMode.MARKDOWN)
    
    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        await self.agent.update_yield()
        status = self.agent.get_status_summary()
        await update.message.reply_text(status, parse_mode=ParseMode.MARKDOWN)
    
    async def cmd_budget(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        await self.agent.update_yield()
        budget = self.agent.get_budget_details()
        await update.message.reply_text(budget, parse_mode=ParseMode.MARKDOWN)
    
    async def cmd_yield(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        await self.agent.update_yield()
        s = self.agent.state
        
        lines = [
            "📈 *Yield Details*", "",
            f"Total Accrued: ${s.accrued_yield_usd:,.2f}",
            f"Already Spent: ${s.spent_from_yield_usd:,.2f}",
            f"Net Available: ${s.accrued_yield_usd - s.spent_from_yield_usd:,.2f}",
            "",
            f"Daily Rate: ${s.total_daily_yield:,.2f}",
            f"Monthly: ${s.total_daily_yield * 30:,.2f}",
            "", "*Sources:*"
        ]
        
        for src in s.yield_sources:
            lines.append(f"• {src.name}: ${src.principal_usd:,.0f} @ {src.apy_percent}%")
        
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    
    async def cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        
        import aiosqlite
        try:
            async with aiosqlite.connect(self.agent.db_path) as db:
                cursor = await db.execute('''
                    SELECT timestamp, amount_usd, token, direction, status, within_budget
                    FROM transactions ORDER BY timestamp DESC LIMIT 10
                ''')
                rows = await cursor.fetchall()
        except:
            rows = []
        
        if not rows:
            await update.message.reply_text("📭 No transactions recorded yet.")
            return
        
        lines = ["📜 *Recent Transactions*", ""]
        for row in rows:
            timestamp, amount, token, direction, status, within_budget = row
            dt = datetime.fromisoformat(timestamp)
            emoji = "📥" if direction == "in" else ("✅" if within_budget else "⚠️")
            lines.append(f"{emoji} ${amount:.2f} {token} - {dt.strftime('%m/%d %H:%M')}")
        
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    
    # ═══════════════════════════════════════════════════════════════
    # SPENDING COMMANDS
    # ═══════════════════════════════════════════════════════════════
    
    async def cmd_spend(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Pre-approve a spending amount"""
        if not await self._check_auth(update):
            return
        
        if not context.args:
            await update.message.reply_text(
                "Usage: `/spend 50` to check if $50 is within your yield budget",
                parse_mode=ParseMode.MARKDOWN)
            return
        
        try:
            amount = float(context.args[0])
        except ValueError:
            await update.message.reply_text(
                "Please enter a valid number, e.g. `/spend 50`",
                parse_mode=ParseMode.MARKDOWN)
            return
        
        await self.agent.update_yield()
        available = float(self.agent.state.available_budget)
        
        if amount <= available:
            remaining = available - amount
            await update.message.reply_text(
                f"✅ *${amount:.2f} APPROVED*\n\n"
                f"Within your yield budget.\n"
                f"Remaining after spend: ${remaining:.2f}\n\n"
                f"Use `/transfer {amount}` to move funds to your Wirex card.",
                parse_mode=ParseMode.MARKDOWN)
        else:
            shortfall = amount - available
            daily_yield = float(self.agent.state.total_daily_yield)
            days_needed = shortfall / daily_yield if daily_yield > 0 else 999
            
            await update.message.reply_text(
                f"❌ *${amount:.2f} DENIED*\n\n"
                f"Exceeds yield budget by ${shortfall:.2f}\n"
                f"Available now: ${available:.2f}\n\n"
                f"⏳ Wait *{days_needed:.1f} days* for enough yield\n"
                f"Or use `/spend {available:.2f}` for max available",
                parse_mode=ParseMode.MARKDOWN)
    
    async def cmd_topup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show available yield for transfer to card"""
        if not await self._check_auth(update):
            return
        
        await self.agent.update_yield()
        s = self.agent.state
        available = float(s.available_budget)
        
        await update.message.reply_text(
            f"💳 *Card Top-up Available*\n\n"
            f"Yield earned: ${float(s.accrued_yield_usd):.2f}\n"
            f"Already spent: ${float(s.spent_from_yield_usd):.2f}\n"
            f"Mode reserve: {int((1 - s.spending_mode.value) * 100)}%\n\n"
            f"✅ *Available to transfer: ${available:.2f}*\n\n"
            f"Use `/transfer {available:.2f}` to move to Wirex card",
            parse_mode=ParseMode.MARKDOWN)
    
    async def cmd_transfer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Execute transfer of yield to Wirex Pay card"""
        if not await self._check_auth(update):
            return
        
        if not context.args:
            await update.message.reply_text(
                "Usage: `/transfer 5` to transfer $5 to your Wirex card",
                parse_mode=ParseMode.MARKDOWN)
            return
        
        try:
            amount = float(context.args[0])
        except ValueError:
            await update.message.reply_text(
                "Please enter a valid number",
                parse_mode=ParseMode.MARKDOWN)
            return
        
        await self.agent.update_yield()
        available = float(self.agent.state.available_budget)
        
        if amount > available:
            await update.message.reply_text(
                f"❌ Cannot transfer ${amount:.2f}\n"
                f"Maximum available from yield: ${available:.2f}",
                parse_mode=ParseMode.MARKDOWN)
            return
        
        # Check executor status
        executor = self._get_executor()
        status = executor.get_status()
        
        if status['usdc_balance'] < amount:
            await update.message.reply_text(
                f"⚠️ *Agent wallet needs funding*\n\n"
                f"Requested: ${amount:.2f}\n"
                f"Agent wallet has: ${status['usdc_balance']:.2f} USDC\n\n"
                f"Please transfer USDC from your Safe to:\n"
                f"`{status['agent_address']}`",
                parse_mode=ParseMode.MARKDOWN)
            return
        
        if status['eth_balance'] < 0.0001:
            await update.message.reply_text(
                f"⚠️ *Agent needs gas*\n\n"
                f"Please send ~0.001 ETH to:\n"
                f"`{status['agent_address']}`",
                parse_mode=ParseMode.MARKDOWN)
            return
        
        # Execute the transfer
        await update.message.reply_text(
            f"⏳ *Executing transfer...*\n\n"
            f"Sending ${amount:.2f} USDC to Wirex Pay...",
            parse_mode=ParseMode.MARKDOWN)
        
        result = await executor.transfer_to_wirex(amount)
        
        if result['success']:
            # Record spending
            self.agent.state.record_spending(Decimal(str(amount)))
            await self.agent.save_state_snapshot()
            
            await update.message.reply_text(
                f"✅ *Transfer Complete!*\n\n"
                f"Sent: ${amount:.2f} USDC\n"
                f"To: Wirex Pay Card\n\n"
                f"🔗 [View on Basescan]({result['explorer_url']})\n\n"
                f"Your card is ready to use! 💳",
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True)
        else:
            await update.message.reply_text(
                f"❌ *Transfer Failed*\n\n"
                f"Error: {result['error']}\n\n"
                f"Please try again or check agent wallet status with /agent",
                parse_mode=ParseMode.MARKDOWN)
    
    async def cmd_agent(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check agent wallet status"""
        if not await self._check_auth(update):
            return
        
        executor = self._get_executor()
        status = executor.get_status()
        
        await update.message.reply_text(
            f"🤖 *Agent Wallet Status*\n\n"
            f"Address: `{status['agent_address']}`\n\n"
            f"💵 USDC: ${status['usdc_balance']:.2f}\n"
            f"⛽ ETH: {status['eth_balance']:.6f}\n\n"
            f"📤 Sends to: `{status['wirex_destination'][:10]}...`",
            parse_mode=ParseMode.MARKDOWN)
    
    # ═══════════════════════════════════════════════════════════════
    # SETTINGS COMMANDS
    # ═══════════════════════════════════════════════════════════════
    
    async def cmd_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        
        if context.args:
            mode_map = {
                'conservative': SpendingMode.CONSERVATIVE,
                'balanced': SpendingMode.BALANCED,
                'growth': SpendingMode.GROWTH
            }
            mode_arg = context.args[0].lower()
            if mode_arg in mode_map:
                self.agent.state.spending_mode = mode_map[mode_arg]
                await self.agent.save_state_snapshot()
                new_mode = self.agent.state.spending_mode
                await update.message.reply_text(
                    f"✅ Mode changed to *{new_mode.name.title()}* ({int(new_mode.value * 100)}%)",
                    parse_mode=ParseMode.MARKDOWN)
                return
        
        keyboard = [[
            InlineKeyboardButton("🐢 Conservative (50%)", callback_data='mode_conservative'),
            InlineKeyboardButton("⚖️ Balanced (80%)", callback_data='mode_balanced'),
            InlineKeyboardButton("🚀 Growth (30%)", callback_data='mode_growth')
        ]]
        
        current = self.agent.state.spending_mode
        await update.message.reply_text(
            f"*Current Mode:* {current.name.title()} ({int(current.value * 100)}%)\n\nSelect new mode:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN)
    
    async def callback_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        mode_map = {
            'mode_conservative': SpendingMode.CONSERVATIVE,
            'mode_balanced': SpendingMode.BALANCED,
            'mode_growth': SpendingMode.GROWTH
        }
        
        if query.data in mode_map:
            self.agent.state.spending_mode = mode_map[query.data]
            await self.agent.save_state_snapshot()
            new_mode = self.agent.state.spending_mode
            await query.edit_message_text(
                f"✅ Mode changed to *{new_mode.name.title()}* ({int(new_mode.value * 100)}%)\n\n"
                f"Available budget: ${self.agent.state.available_budget:,.2f}",
                parse_mode=ParseMode.MARKDOWN)
    
    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        
        help_text = """🛡️ *Yield Guardian Commands*

*💰 Spending:*
/spend <amount> - Check if amount is within budget
/topup - See available yield for card
/transfer <amount> - Send yield to Wirex card

*📊 Status:*
/status - Overview of balances & budget
/budget - Detailed budget breakdown
/yield - Yield accrual details
/history - Recent transactions

*⚙️ Settings:*
/mode - Change spending mode
/agent - Agent wallet status
/help - This message

*Spending Modes:*
🐢 Conservative - Spend 50% of yield
⚖️ Balanced - Spend 80% of yield
🚀 Growth - Spend 30% of yield"""
        
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    
    # ═══════════════════════════════════════════════════════════════
    # ALERTS
    # ═══════════════════════════════════════════════════════════════
    
    async def send_alert(self, message: str):
        if self.app and self.authorized_user_id:
            try:
                await self.app.bot.send_message(
                    chat_id=self.authorized_user_id,
                    text=message,
                    parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                logger.error(f"Failed to send alert: {e}")
    
    async def send_transaction_alert(self, tx: Transaction, is_within_budget: bool, message: str):
        emoji = "✅" if is_within_budget else "🚨"
        alert = f"""{emoji} *Transaction Detected*

Amount: ${tx.amount_usd:.2f} {tx.token}
Status: {message}
Time: {tx.timestamp.strftime('%Y-%m-%d %H:%M')}

Budget: ${self.agent.state.available_budget:,.2f} remaining"""
        await self.send_alert(alert)
    
    # ═══════════════════════════════════════════════════════════════
    # SETUP
    # ═══════════════════════════════════════════════════════════════
    
    def setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("budget", self.cmd_budget))
        self.app.add_handler(CommandHandler("yield", self.cmd_yield))
        self.app.add_handler(CommandHandler("history", self.cmd_history))
        self.app.add_handler(CommandHandler("spend", self.cmd_spend))
        self.app.add_handler(CommandHandler("topup", self.cmd_topup))
        self.app.add_handler(CommandHandler("transfer", self.cmd_transfer))
        self.app.add_handler(CommandHandler("agent", self.cmd_agent))
        self.app.add_handler(CommandHandler("mode", self.cmd_mode))
        self.app.add_handler(CommandHandler("help", self.cmd_help))
        self.app.add_handler(CallbackQueryHandler(self.callback_mode, pattern="^mode_"))
    
    async def start(self):
        self.app = Application.builder().token(self.token).build()
        self.setup_handlers()
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot started")
        await self.send_alert("🛡️ *Yield Guardian Started!*\n\nMonitoring your wallet.\nSend /status to check.")
    
    async def stop(self):
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
