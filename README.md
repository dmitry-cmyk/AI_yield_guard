# 🛡️ Yield Guardian Agent

**An AI agent that enforces "spend only from yield" rules using self-custody and smart contracts.**

Built for use with [Wirex Pay](https://wirexapp.com/wirex-pay) self-custody cards on Base chain.

---

## 🎯 What It Does

Traditional budgeting relies on willpower. Yield Guardian makes overspending **mathematically impossible**.

- 💰 **Tracks yield** from DeFi protocols (Aave V3) in real-time
- 🔒 **Protects principal** using Safe smart wallet spending limits
- 🤖 **AI agent** approves/denies purchases based on available yield
- 💳 **Auto-transfers** approved amounts to your Wirex Pay card
- 📱 **Telegram interface** for easy control

```
You: /spend 50
Bot: ✅ $50 APPROVED - Within your yield budget
     Use /transfer 50 to move funds to your card

You: /spend 1000  
Bot: ❌ $1000 DENIED - Exceeds budget by $944
     Wait 87 days for enough yield, or use /spend 56 for max available
```

---

## 🏗️ Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Your Wallet   │     │   Safe Wallet    │     │   Wirex Pay     │
│   (MetaMask)    │────▶│  + Aave Position │────▶│   Card Wallet   │
│   Full Control  │     │  + Spending Limit│     │                 │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │
                               │ Agent can only
                               │ transfer yield
                               ▼
                        ┌──────────────────┐
                        │  Yield Guardian  │
                        │     Agent        │
                        │  (Telegram Bot)  │
                        └──────────────────┘
```

**Key Security Features:**
- Principal stays in Aave, earning yield
- Safe spending limit caps what agent can access
- Agent wallet has limited permissions
- You retain full control via MetaMask

---

## 📋 Prerequisites

- Python 3.11+
- A [Wirex](https://web3.wirexapp.com) account with Wirex Pay enabled
- MetaMask wallet with some USDC on Base chain
- Telegram account (for bot interface)

---

## 🚀 Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/YOUR_USERNAME/yield-guardian-agent.git
cd yield-guardian-agent
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Create Telegram Bot

1. Message [@BotFather](https://t.me/botfather) on Telegram
2. Send `/newbot` and follow prompts
3. Save the bot token

Get your Telegram user ID:
1. Message [@userinfobot](https://t.me/userinfobot)
2. Save the ID it returns

### 3. Set Up Safe Wallet

1. Go to [Safe](https://app.safe.global)
2. Create a new Safe on **Base** network
3. Your MetaMask becomes the owner

### 4. Deposit to Aave (via Safe)

1. In Safe, go to **Apps** → **Aave**
2. Supply your USDC to Aave V3
3. This is your protected principal

### 5. Create Agent Wallet

```bash
python3 create_agent_wallet.py
```

Save the address and private key securely. See [Security](#-security) for how to store the private key.

### 6. Set Up Spending Limit

1. In Safe → **Settings** → **Spending limits**
2. Add new limit:
   - Beneficiary: `<agent wallet address>`
   - Token: USDC
   - Amount: 10 (or your weekly yield)
   - Reset: Weekly

### 7. Configure

```bash
cp config.example.yaml config.yaml
# Edit config.yaml with your values (except private key - see Security section)
```

### 8. Set Environment Variable

Store the agent private key as an environment variable (never in config files):

```bash
export AGENT_PRIVATE_KEY="your_private_key_here"
```

For production deployment, add to your systemd service file (see [Deployment](#️-deployment)).

### 9. Fund Agent Wallet

Send to your agent wallet address:
- Small amount of USDC (e.g., $5-10)
- Tiny amount of ETH for gas (~0.001 ETH on Base)

### 10. Run

```bash
python main.py
```

Or deploy to a server for 24/7 operation (see [Deployment](#️-deployment)).

---

## 📱 Telegram Commands

| Command | Description |
|---------|-------------|
| `/status` | Overview of balances & budget |
| `/spend <amount>` | Check if amount is within yield budget |
| `/transfer <amount>` | Send USDC to Wirex Pay card |
| `/topup` | See available yield for transfer |
| `/budget` | Detailed budget breakdown |
| `/yield` | Yield accrual details |
| `/agent` | Check agent wallet status |
| `/mode` | Change spending mode |
| `/help` | All commands |

**Spending Modes:**
- 🐢 **Conservative** - Spend 50% of yield, save 50%
- ⚖️ **Balanced** - Spend 80% of yield, save 20%
- 🚀 **Growth** - Spend 30% of yield, reinvest 70%

---

## 🔧 Configuration

```yaml
# config.yaml

# Safe wallet (holds your Aave position)
safe_address: "0x..."

# Agent wallet address (private key stored in environment variable)
agent_wallet_address: "0x..."

# Wirex Pay card wallet
wirex_pay_address: "0x..."

# Telegram bot
telegram:
  bot_token: "123456:ABC..."
  authorized_user_id: 12345678

# Your principal amount
principal_usd: 10000

# Spending mode: conservative, balanced, growth
spending_mode: "balanced"

# Yield sources
yield_sources:
  - name: "Aave V3 USDC"
    type: "aave_v3"
    principal_usd: 10000
    apy_percent: 3.91
```

---

## 🖥️ Deployment

### Option A: DigitalOcean Droplet (Recommended)

1. Create Ubuntu 24.04 droplet ($6/month)
2. SSH in and clone repo
3. Set up as systemd service:

```bash
sudo cat > /etc/systemd/system/yield-guardian.service << EOF
[Unit]
Description=Yield Guardian Agent
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/yield-guardian
Environment="AGENT_PRIVATE_KEY=your_private_key_here"
ExecStart=/opt/yield-guardian/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable yield-guardian
sudo systemctl start yield-guardian
```

### Option B: Railway/Render

Deploy directly from GitHub with one click. Set `AGENT_PRIVATE_KEY` in the environment variables section of your deployment platform.

---

## 🔐 Security

### Agent Private Key

The agent wallet private key should **never** be stored in config files or committed to Git.

**Use environment variables:**

```bash
# Local development
export AGENT_PRIVATE_KEY="your_private_key_here"

# Production (systemd)
Environment="AGENT_PRIVATE_KEY=your_private_key_here"
```

### Risk Mitigation

The agent wallet has **limited exposure** by design:

| What | Risk Level | Why |
|------|------------|-----|
| Agent wallet | Low | Only holds your weekly allowance ($10) |
| Safe wallet | Protected | Agent cannot access directly |
| Aave principal | Protected | Requires Safe owner signature |

**If the agent key is compromised**, maximum loss = current agent wallet balance (not your principal).

### Best Practices

1. **Never commit secrets** — `config.yaml` is in `.gitignore`
2. **Use environment variables** — for all private keys
3. **Limit server access** — use SSH keys, disable password auth
4. **Keep spending limits low** — only what you need weekly
5. **Monitor transactions** — check Basescan for agent activity

The agent **cannot**:
- Access your Aave position directly
- Exceed the spending limit you set
- Send to addresses other than Wirex Pay
- Modify Safe settings

---

## 🛣️ Roadmap

- [ ] Multi-protocol yield tracking (Morpho, Compound)
- [ ] Automatic yield harvesting
- [ ] Subscription detection and alerts
- [ ] Spending analytics dashboard
- [ ] Multi-chain support

---

## 🤝 Contributing

PRs welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## 📄 License

MIT License - see [LICENSE](LICENSE)

---

## 🙏 Acknowledgments

- [Wirex](https://web3.wirexapp.com), [Wirex Developers](https://www.wirexapp.com/developers) for self-custody card infrastructure
- [Safe](https://safe.global) for smart wallet security
- [Aave](https://aave.com) for DeFi yield
- Built with Claude AI assistance

---

## ⚠️ Disclaimer

This is experimental software. Use at your own risk. Not financial advice. Always test with small amounts first.

