// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title AgentPayEscrow
/// @notice Trustless USDC escrow for AI agent task settlement on Base.
/// @dev    Funds are held 1:1 in this contract. Only the fee recipient
///         (separately operated) lends the accumulated fee float to Aave
///         so the escrow principal itself is never lent. Anyone can read
///         the contract; writes are by payer, payee, or owner.
contract AgentPayEscrow {
    enum Status { None, Funded, Released, Refunded }

    struct Escrow {
        address payer;
        address payee;
        address token;       // USDC (or any ERC20)
        uint256 amount;      // principal
        uint256 fee;         // platform fee at release time
        bytes32 taskHash;    // opaque identifier of the work
        uint64  deadline;    // unix seconds; refundable after this
        uint8   status;      // Status enum
    }

    address public owner;
    address public feeRecipient;
    uint256 public feeBps;  // basis points, 50 = 0.5%
    uint256 public constant BPS_DENOM = 10_000;
    uint256 public constant MAX_FEE_BPS = 500; // hard cap 5%

    mapping(bytes32 => Escrow) public escrows;
    bytes32[] public escrowIds;

    event EscrowCreated(
        bytes32 indexed id,
        address indexed payer,
        address indexed payee,
        address token,
        uint256 amount,
        bytes32 taskHash,
        uint64 deadline
    );
    event EscrowFunded(bytes32 indexed id);
    event EscrowReleased(bytes32 indexed id, address indexed payee, uint256 netAmount, uint256 fee);
    event EscrowRefunded(bytes32 indexed id, address indexed payer, uint256 amount);
    event FeeBpsUpdated(uint256 oldBps, uint256 newBps);
    event FeeRecipientUpdated(address indexed oldRcp, address indexed newRcp);
    event OwnershipTransferred(address indexed oldOwner, address indexed newOwner);

    error NotOwner();
    error NotAuthorized();
    error EscrowNotFound();
    error InvalidState();
    error InvalidParams();
    error TransferFailed();

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    constructor(address _feeRecipient, uint256 _feeBps) {
        if (_feeRecipient == address(0)) revert InvalidParams();
        if (_feeBps > MAX_FEE_BPS) revert InvalidParams();
        owner = msg.sender;
        feeRecipient = _feeRecipient;
        feeBps = _feeBps;
        emit OwnershipTransferred(address(0), msg.sender);
        emit FeeRecipientUpdated(address(0), _feeRecipient);
        emit FeeBpsUpdated(0, _feeBps);
    }

    /// @notice Create + fund an escrow in a single transaction.
    /// @dev    Caller must `approve` this contract for `amount` of `token` first.
    function createAndFund(
        address payee,
        address token,
        uint256 amount,
        bytes32 taskHash,
        uint64  deadline
    ) external returns (bytes32 id) {
        if (payee == address(0) || token == address(0)) revert InvalidParams();
        if (amount == 0) revert InvalidParams();
        if (deadline <= block.timestamp) revert InvalidParams();
        if (taskHash == bytes32(0)) revert InvalidParams();

        // Pull USDC from payer to this contract.
        (bool ok, bytes memory data) = token.call(
            abi.encodeWithSelector(0x23b872dd /* transferFrom */, msg.sender, address(this), amount)
        );
        if (!ok || (data.length != 0 && !abi.decode(data, (bool)))) revert TransferFailed();

        uint256 fee = (amount * feeBps) / BPS_DENOM;
        id = keccak256(
            abi.encodePacked(msg.sender, payee, token, amount, taskHash, deadline, block.timestamp, escrowIds.length)
        );
        escrows[id] = Escrow({
            payer: msg.sender,
            payee: payee,
            token: token,
            amount: amount,
            fee: fee,
            taskHash: taskHash,
            deadline: deadline,
            status: uint8(Status.Funded)
        });
        escrowIds.push(id);

        emit EscrowCreated(id, msg.sender, payee, token, amount, taskHash, deadline);
        emit EscrowFunded(id);
    }

    /// @notice Release escrow to payee. Caller must be payer or owner.
    function release(bytes32 id) external {
        Escrow storage e = escrows[id];
        if (e.status != uint8(Status.Funded)) revert InvalidState();
        if (msg.sender != e.payer && msg.sender != owner) revert NotAuthorized();

        e.status = uint8(Status.Released);
        uint256 netAmount = e.amount - e.fee;

        _transfer(e.token, e.payee, netAmount);
        if (e.fee > 0) _transfer(e.token, feeRecipient, e.fee);

        emit EscrowReleased(id, e.payee, netAmount, e.fee);
    }

    /// @notice Refund escrow to payer. Allowed after deadline, or by payer/owner any time.
    function refund(bytes32 id) external {
        Escrow storage e = escrows[id];
        if (e.status != uint8(Status.Funded)) revert InvalidState();
        bool allowed =
            msg.sender == e.payer ||
            msg.sender == owner ||
            block.timestamp >= e.deadline;
        if (!allowed) revert NotAuthorized();

        e.status = uint8(Status.Refunded);
        _transfer(e.token, e.payer, e.amount);

        emit EscrowRefunded(id, e.payer, e.amount);
    }

    function getEscrow(bytes32 id) external view returns (Escrow memory) {
        return escrows[id];
    }

    function totalEscrows() external view returns (uint256) {
        return escrowIds.length;
    }

    // --- admin ---

    function setFeeBps(uint256 newBps) external onlyOwner {
        if (newBps > MAX_FEE_BPS) revert InvalidParams();
        emit FeeBpsUpdated(feeBps, newBps);
        feeBps = newBps;
    }

    function setFeeRecipient(address newRcp) external onlyOwner {
        if (newRcp == address(0)) revert InvalidParams();
        emit FeeRecipientUpdated(feeRecipient, newRcp);
        feeRecipient = newRcp;
    }

    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert InvalidParams();
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    // --- internal ---

    function _transfer(address token, address to, uint256 amount) internal {
        (bool ok, bytes memory data) = token.call(
            abi.encodeWithSelector(0xa9059cbb /* transfer */, to, amount)
        );
        if (!ok || (data.length != 0 && !abi.decode(data, (bool)))) revert TransferFailed();
    }
}
