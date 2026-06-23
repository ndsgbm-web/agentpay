// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @notice Minimal interfaces (Aave v3 Pool, USDC).
interface IERC20 {
    function balanceOf(address) external view returns (uint256);
    function transfer(address, uint256) external returns (bool);
    function transferFrom(address, address, uint256) external returns (bool);
    function approve(address, uint256) external returns (bool);
    function decimals() external view returns (uint8);
}

interface IAavePool {
    function supply(address asset, uint256 amount, address onBehalfOf, uint16 referralCode) external;
    function withdraw(address asset, uint256 amount, address to) external returns (uint256);
    function getReserveData(address asset) external view returns (ReserveDataLegacy memory);
}

struct ReserveDataLegacy {
    ReserveConfigurationMap configuration;
    uint128 liquidityIndex;
    uint128 currentLiquidityRate;
    uint128 variableBorrowIndex;
    uint128 currentVariableBorrowRate;
    uint128 currentStableBorrowRate;
    uint40 lastUpdateTimestamp;
    uint16 id;
    address aTokenAddress;
    address stableDebtTokenAddress;
    address variableDebtTokenAddress;
    address interestRateStrategyAddress;
    uint128 accruedToTreasury;
    uint128 unbacked;
    uint128 isolationModeTotalDebt;
}

struct ReserveConfigurationMap { uint256 data; }

/// @title AgentPayVault
/// @notice USDC collateral pool with Aave v3 supply + per-agent yield accounting.
/// @dev    Deposits go straight to Aave and become aUSDC. The vault tracks
///         per-agent aToken shares. Yield (aToken - principal) is split
///         skimBps/10000 to the protocol; the rest stays for the depositor.
contract AgentPayVault {
    /// @notice USDC token (Base mainnet: 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913).
    address public immutable usdc;
    /// @notice Aave v3 Pool (Base mainnet: 0xA238Dd80C259a72e81d7e4664a9801593F98d1c5).
    IAavePool public immutable aave;
    /// @notice aUSDC token, set on first deposit.
    address public aUsdc;

    address public owner;
    /// @notice Protocol address that receives the yield skim.
    address public yieldRecipient;
    /// @notice Task escrow contract; only it can lock/slash stake.
    address public taskManager;

    /// @dev Skim 30% of accrued yield to the protocol; 70% stays for depositors.
    uint256 public yieldSkimBps = 3000;
    /// @dev Cap per-agent aToken exposure per single deposit (anti-flash-loan).
    uint256 public maxDeposit = 1_000_000_000_000; // 1B USDC (sanity)

    struct Position {
        uint256 aTokenShares;   // 1:1 with aUSDC balance this agent owns
        uint256 lockedStake;    // aTokens currently locked in open tasks
        uint256 yieldDebt;      // yield already paid out to this agent
    }

    mapping(address => Position) public positions;
    uint256 public totalShares;       // sum of all aTokenShares
    uint256 public totalYieldPaid;    // lifetime yield distributed to depositors
    uint256 public totalYieldSkimmed; // lifetime yield skimmed to protocol

    event Deposit(address indexed agent, uint256 usdcAmount, uint256 aTokens);
    event Withdraw(address indexed agent, uint256 usdcAmount, uint256 aTokens);
    event StakeLocked(address indexed agent, uint256 amount, bytes32 indexed taskId);
    event StakeReleased(address indexed agent, uint256 amount, bytes32 indexed taskId);
    event StakeSlashed(address indexed agent, address indexed to, uint256 amount, bytes32 indexed taskId);
    event YieldSkimmed(address indexed to, uint256 amount);
    event TaskManagerUpdated(address indexed oldTM, address indexed newTM);
    event YieldRecipientUpdated(address indexed oldR, address indexed newR);
    event YieldSkimBpsUpdated(uint256 oldBps, uint256 newBps);
    event OwnershipTransferred(address indexed oldOwner, address indexed newOwner);

    error NotOwner();
    error NotTaskManager();
    error NotAgent();
    error InvalidParams();
    error InsufficientBalance();
    error StakeInUse();
    error TransferFailed();

    modifier onlyOwner() { if (msg.sender != owner) revert NotOwner(); _; }
    modifier onlyTaskManager() { if (msg.sender != taskManager) revert NotTaskManager(); _; }

    constructor(address _usdc, address _aave, address _yieldRecipient) {
        if (_usdc == address(0) || _aave == address(0) || _yieldRecipient == address(0)) revert InvalidParams();
        usdc = _usdc;
        aave = IAavePool(_aave);
        yieldRecipient = _yieldRecipient;
        owner = msg.sender;
    }

    /// @notice Discover aUSDC address (call once after deploy).
    function init() public {
        if (aUsdc != address(0)) return;
        ReserveDataLegacy memory d = aave.getReserveData(usdc);
        aUsdc = d.aTokenAddress;
        // Pre-approve the pool to pull USDC from us.
        (bool ok, ) = usdc.call(abi.encodeWithSelector(0x095ea7b3, aave, type(uint256).max));
        require(ok, "approve failed");
    }

    // ---------- depositor path ----------

    /// @notice Deposit USDC. Pulls from msg.sender, supplies to Aave.
    function deposit(uint256 usdcAmount) external returns (uint256 aTokensOut) {
        if (usdcAmount == 0 || usdcAmount > maxDeposit) revert InvalidParams();
        if (aUsdc == address(0)) { init(); }

        (bool ok, ) = usdc.call(abi.encodeWithSelector(0x23b872dd, msg.sender, address(this), usdcAmount));
        if (!ok) revert TransferFailed();

        uint256 aBefore = IERC20(aUsdc).balanceOf(address(this));
        aave.supply(usdc, usdcAmount, address(this), 0);
        uint256 aAfter = IERC20(aUsdc).balanceOf(address(this));
        aTokensOut = aAfter - aBefore;

        positions[msg.sender].aTokenShares += aTokensOut;
        totalShares += aTokensOut;

        emit Deposit(msg.sender, usdcAmount, aTokensOut);
    }

    /// @notice Withdraw USDC. Burns your share of aTokens, returns USDC.
    function withdraw(uint256 usdcAmount) external returns (uint256 aTokensBurned) {
        Position storage p = positions[msg.sender];
        if (usdcAmount == 0) revert InvalidParams();

        // share of yield accrued to this position
        uint256 aBalance = aTokenBalanceOf(msg.sender);
        // cannot withdraw if portion locked
        uint256 aLocked = p.lockedStake;       // 1:1 in USDC units (aUSDC is rebasing)
        if (aBalance - aLocked < _usdcToShares(usdcAmount, aBalance, p.aTokenShares)) revert StakeInUse();

        aTokensBurned = aave.withdraw(usdc, usdcAmount, msg.sender);
        p.aTokenShares -= aTokensBurned;
        totalShares -= aTokensBurned;

        emit Withdraw(msg.sender, usdcAmount, aTokensBurned);
    }

    function _usdcToShares(uint256 usdcAmount, uint256 aBalance, uint256 aShares) internal pure returns (uint256) {
        if (aShares == 0) return 0;
        return (usdcAmount * aShares) / aBalance;
    }

    /// @notice aUSDC-equivalent USDC balance for an agent (principal + accrued yield share).
    function aTokenBalanceOf(address agent) public view returns (uint256) {
        Position storage p = positions[agent];
        if (totalShares == 0) return 0;
        uint256 aUsdcTotal = IERC20(aUsdc).balanceOf(address(this));
        return (aUsdcTotal * p.aTokenShares) / totalShares;
    }

    // ---------- task manager path ----------

    function setTaskManager(address tm) external onlyOwner {
        if (tm == address(0)) revert InvalidParams();
        emit TaskManagerUpdated(taskManager, tm);
        taskManager = tm;
    }

    function lockStake(address agent, uint256 usdcAmount, bytes32 taskId) external onlyTaskManager {
        if (usdcAmount == 0) revert InvalidParams();
        uint256 aBalance = aTokenBalanceOf(agent);
        if (aBalance < usdcAmount) revert InsufficientBalance();
        positions[agent].lockedStake += usdcAmount;
        emit StakeLocked(agent, usdcAmount, taskId);
    }

    function releaseStake(address agent, uint256 usdcAmount, bytes32 taskId) external onlyTaskManager {
        if (usdcAmount == 0) revert InvalidParams();
        Position storage p = positions[agent];
        if (p.lockedStake < usdcAmount) revert InsufficientBalance();
        p.lockedStake -= usdcAmount;
        emit StakeReleased(agent, usdcAmount, taskId);
    }

    /// @notice Slash an agent's stake and pay it to `to` (the task buyer).
    function slash(address agent, address to, uint256 usdcAmount, bytes32 taskId) external onlyTaskManager {
        if (usdcAmount == 0 || to == address(0)) revert InvalidParams();
        Position storage p = positions[agent];
        if (p.lockedStake < usdcAmount) revert InsufficientBalance();
        p.lockedStake -= usdcAmount;
        aave.withdraw(usdc, usdcAmount, to);
        emit StakeSlashed(agent, to, usdcAmount, taskId);
    }

    // ---------- yield skim ----------

    /// @notice Anyone can call to skim accrued yield. 30% to yieldRecipient; 70% remains for depositors.
    function skimYield() external {
        if (aUsdc == address(0)) return;
        uint256 aUsdcTotal = IERC20(aUsdc).balanceOf(address(this));
        // total principal tracked in shares; aUsdcTotal - principal = yield
        if (aUsdcTotal <= totalShares) return;  // no yield yet
        uint256 yieldAccrued = aUsdcTotal - totalShares;
        uint256 skim = (yieldAccrued * yieldSkimBps) / 10_000;
        if (skim == 0) return;
        aave.withdraw(usdc, skim, yieldRecipient);
        totalShares = IERC20(aUsdc).balanceOf(address(this));  // refresh
        totalYieldSkimmed += skim;
        emit YieldSkimmed(yieldRecipient, skim);
    }

    // ---------- admin ----------

    function setYieldSkimBps(uint256 newBps) external onlyOwner {
        if (newBps > 5_000) revert InvalidParams();
        emit YieldSkimBpsUpdated(yieldSkimBps, newBps);
        yieldSkimBps = newBps;
    }

    function setYieldRecipient(address r) external onlyOwner {
        if (r == address(0)) revert InvalidParams();
        emit YieldRecipientUpdated(yieldRecipient, r);
        yieldRecipient = r;
    }

    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert InvalidParams();
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }
}
