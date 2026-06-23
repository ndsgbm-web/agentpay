# Deploying AgentPay to Base

## Pre-flight

- A deployer wallet with at least 0.005 ETH on Base (for gas)
- The compiled bytecode already lives in `build/` (regenerate with `solcjs`)
- Optional: a BaseScan API key for contract verification

## 1. Compile (only if you change the contract)

```bash
cd agentpay
node_modules/.bin/solcjs contracts/AgentPayEscrow.sol contracts/MockUSDC.sol \
    --bin --abi -o build
```

The `build/` directory is gitignored.

## 2. Deploy to Base Sepolia (testnet)

Get testnet ETH from https://www.alchemy.com/faucets/base-sepolia (free,
~0.5 ETH per 24h).

```bash
export DEPLOYER_KEY=0x...
export AGENTPAY_RECIPIENT=0xYourFeeRecipientOnBase   # your USDC address

python scripts/deploy.py \
    --private-key $DEPLOYER_KEY \
    --network base-sepolia \
    --fee-recipient $AGENTPAY_RECIPIENT \
    --fee-bps 50
```

The script prints:
- The deployed contract address
- A BaseScan link

## 3. Deploy to Base mainnet

```bash
export DEPLOYER_KEY=0x...    # real key, real ETH
export AGENTPAY_RECIPIENT=0xYourMainnetUSDCAddress

python scripts/deploy.py \
    --private-key $DEPLOYER_KEY \
    --network base \
    --fee-recipient $AGENTPAY_RECIPIENT \
    --fee-bps 50 \
    --verify \
    --etherscan-key $BASESCAN_API_KEY
```

The `--verify` flag uploads the source to BaseScan so the contract tab
shows the Solidity.

## 4. Use it

```python
from agentpay import AgentPay
ap = AgentPay(
    private_key="0x...",
    escrow_address="0xDeployedAddress...",  # from step 2 or 3
    chain_id=8453,                         # or 84532 for Sepolia
)
```

## What's deployed

A single contract `AgentPayEscrow` with:
- `createAndFund(payee, token, amount, taskHash, deadline)` — buyer locks USDC
- `release(id)` — buyer signs, USDC to seller + 0.5% to feeRecipient
- `refund(id)` — refund back to payer (after deadline, or by payer/owner)
- `setFeeBps(newBps)` / `setFeeRecipient(newAddr)` — owner only, capped at 5%
- `transferOwnership(newOwner)` — owner only

The 0.5% fee accumulates in the feeRecipient wallet. To start earning
Aave yield on the float, the feeRecipient owner (you) supplies the
USDC to Aave v3 on Base:

```python
# pseudo-code; Aave ABI omitted for brevity
aave_pool.supply(usdc_address, balance, recipient, 0)
```

The contract itself **never** lends user funds. The fee float is in
your control; you choose to lend it or not.
