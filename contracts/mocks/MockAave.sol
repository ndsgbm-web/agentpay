// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IERC20Ext {
    function transfer(address, uint256) external returns (bool);
    function transferFrom(address, address, uint256) external returns (bool);
    function balanceOf(address) external view returns (uint256);
    function mint(address, uint256) external;
}

/// @title MockAave — minimal Aave v3 Pool stub for AgentPay tests
/// @notice Vault is the only supplier. Tracks per-address aUSDC balance
///         that vault reads via IERC20(aTokenAddress).balanceOf(vault).
contract MockAave {
    address public usdc;
    address public vault;     // set once after deploy
    address public aTokenAddress; // points to this contract itself

    // pretend aUSDC balances (read by vault)
    mapping(address => uint256) public aUSDCBalance;
    uint256 public totalAUSDC;

    struct ReserveData {
        uint256 configuration;
        uint128 liquidityIndex;
        uint128 currentLiquidityRate;
        uint128 variableBorrowIndex;
        uint128 currentVariableBorrowRate;
        uint128 currentStableBorrowRate;
        uint40  lastUpdateTimestamp;
        uint16  id;
        address aTokenAddress;
        address stableDebtTokenAddress;
        address variableDebtTokenAddress;
        address interestRateStrategyAddress;
        uint128 accruedToTreasury;
        uint128 unbacked;
        uint128 isolationModeTotalDebt;
    }

    constructor(address _usdc) {
        usdc = _usdc;
        aTokenAddress = address(this);  // we ARE the aUSDC for the vault
    }

    function setVault(address v) external {
        require(vault == address(0), "vault set");
        vault = v;
    }

    /// @notice IERC20-like balanceOf so vault can call IERC20(aUsdc).balanceOf(vault).
    function balanceOf(address who) external view returns (uint256) {
        return aUSDCBalance[who];
    }

    /// @notice IERC20-like transfer for completeness.
    function transfer(address to, uint256 amount) external returns (bool) {
        aUSDCBalance[msg.sender] -= amount;
        aUSDCBalance[to]        += amount;
        return true;
    }

    function getReserveData(address) external view returns (ReserveData memory) {
        ReserveData memory d;
        d.aTokenAddress = aTokenAddress;
        d.liquidityIndex = 1e27;            // pretend index so aTokens ≈ USDC
        d.currentLiquidityRate = 30_000_000_000; // pretend ~3% APR in ray/sec-ish
        return d;
    }

    /// @notice Supply USDC into the pool. Pulls USDC from caller, bumps vault's aUSDC.
    function supply(address asset, uint256 amount, address onBehalfOf, uint16) external {
        require(asset == usdc, "wrong asset");
        require(onBehalfOf == vault, "supply to vault only");
        // pull USDC
        (bool ok, bytes memory ret) = usdc.call(
            abi.encodeWithSelector(IERC20Ext.transferFrom.selector, msg.sender, address(this), amount)
        );
        require(ok && (ret.length == 0 || abi.decode(ret, (bool))), "pull failed");
        aUSDCBalance[vault] += amount;
        totalAUSDC           += amount;
    }

    /// @notice Withdraw USDC from the pool to `to`. Burns vault's aUSDC.
    function withdraw(address asset, uint256 amount, address to) external returns (uint256) {
        require(asset == usdc, "wrong asset");
        require(msg.sender == vault, "only vault");
        require(aUSDCBalance[vault] >= amount, "no balance");
        aUSDCBalance[vault] -= amount;
        totalAUSDC          -= amount;
        (bool ok, bytes memory ret) = usdc.call(
            abi.encodeWithSelector(IERC20Ext.transfer.selector, to, amount)
        );
        require(ok && (ret.length == 0 || abi.decode(ret, (bool))), "push failed");
        return amount;
    }

    /// @notice TEST-ONLY: bump vault's aUSDC by `amount` to simulate yield.
    /// @dev    Mints USDC into this contract (representing yield distributed by Aave),
    ///         then bumps the vault's aUSDC balance. No approval flow required.
    function accrueYield(uint256 amount) external {
        // mint USDC to self so skimYield can pull it out via withdraw()
        IERC20Ext(usdc).mint(address(this), amount);
        aUSDCBalance[vault] += amount;
        totalAUSDC          += amount;
    }
}
