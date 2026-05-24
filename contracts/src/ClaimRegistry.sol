// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Minimal ERC-20 surface used for bond settlement (USDC on Arc).
interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
}

/// @title ClaimRegistry — AKRITA Rugpull Oracle
/// @notice Append-only registry of signed "rug risk" claims sourced from the
///         NostalgiaForInfinity blacklist feed. Each claim links a token to its
///         GitHub provenance (`sourceCommit`) and to an on-chain reasoning trace
///         (`traceHash` + `ipfsCid`, anchored separately in TraceRegistry), and
///         carries an optional two-sided USDC bond market: stakers bond for or
///         against "will TOKEN drop > dropThresholdBps within `window`?". On
///         resolution the losing side is slashed pro-rata to the winners.
/// @dev No OpenZeppelin; mirrors TraceRegistry's owner + authorized-mapping style.
///      Trace anchoring stays in TraceRegistry — the two contracts compose.
contract ClaimRegistry {
    uint8 internal constant STATUS_OPEN = 0;
    uint8 internal constant STATUS_RUGGED = 1; // claim resolved TRUE (token rugged)
    uint8 internal constant STATUS_SAFE = 2; // claim resolved FALSE (token held)

    struct Claim {
        bytes32 tokenId; // keccak256("TOKEN/QUOTE@exchange")
        bytes32 sourceCommit; // NFI git commit that added the blacklist entry
        bytes32 traceHash; // sha256(canonical reasoning trace) — see TraceRegistry
        string ipfsCid; // full trace body (CIDv1)
        address issuer; // authorized claim-issuing keeper (NOMOS)
        uint64 issuedAt;
        uint64 window; // seconds the prediction covers (e.g. 7 days)
        uint16 dropThresholdBps; // e.g. 5000 = "will drop >50%"
        uint8 status; // STATUS_OPEN | STATUS_RUGGED | STATUS_SAFE
        uint64 resolvedAt;
    }

    struct Bond {
        uint256 forStake; // total staked that the claim resolves TRUE (rug)
        uint256 againstStake; // total staked that it resolves FALSE
    }

    address public owner;
    IERC20 public immutable bondToken; // USDC on Arc
    mapping(address => bool) public authorizedIssuers;
    mapping(address => bool) public authorizedResolvers;

    uint256 public totalClaims;
    mapping(uint256 => Claim) public claims;
    mapping(uint256 => Bond) public bonds;
    mapping(uint256 => mapping(address => uint256)) public forOf;
    mapping(uint256 => mapping(address => uint256)) public againstOf;
    mapping(uint256 => mapping(address => bool)) public withdrawnOf;

    event ClaimIssued(
        uint256 indexed claimId,
        bytes32 indexed tokenId,
        bytes32 sourceCommit,
        bytes32 traceHash,
        string ipfsCid,
        uint64 window,
        uint16 dropThresholdBps
    );
    event Staked(uint256 indexed claimId, address indexed staker, bool backsClaim, uint256 amount);
    event Resolved(uint256 indexed claimId, uint8 status, uint64 resolvedAt);
    event Payout(uint256 indexed claimId, address indexed staker, uint256 amount);
    event IssuerAuthorized(address indexed who, bool authorized);
    event ResolverAuthorized(address indexed who, bool authorized);

    error NotOwner(address caller);
    error NotIssuer(address caller);
    error NotResolver(address caller);
    error NoSuchClaim(uint256 claimId);
    error NotOpen(uint256 claimId);
    error AlreadyResolved(uint256 claimId);
    error NotResolvedYet(uint256 claimId);
    error AlreadyWithdrawn(uint256 claimId);
    error ZeroAmount();
    error TransferFailed();

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner(msg.sender);
        _;
    }

    modifier onlyIssuer() {
        if (!authorizedIssuers[msg.sender]) revert NotIssuer(msg.sender);
        _;
    }

    modifier onlyResolver() {
        if (!authorizedResolvers[msg.sender]) revert NotResolver(msg.sender);
        _;
    }

    constructor(address bondToken_) {
        owner = msg.sender;
        bondToken = IERC20(bondToken_);
        authorizedIssuers[msg.sender] = true;
        authorizedResolvers[msg.sender] = true;
    }

    function setIssuer(address who, bool authorized) external onlyOwner {
        authorizedIssuers[who] = authorized;
        emit IssuerAuthorized(who, authorized);
    }

    function setResolver(address who, bool authorized) external onlyOwner {
        authorizedResolvers[who] = authorized;
        emit ResolverAuthorized(who, authorized);
    }

    /// @notice Issue a signed rug-risk claim. Trace must already be anchored.
    function issueClaim(
        bytes32 tokenId,
        bytes32 sourceCommit,
        bytes32 traceHash,
        string calldata ipfsCid,
        uint64 window,
        uint16 dropThresholdBps
    ) external onlyIssuer returns (uint256 claimId) {
        totalClaims += 1;
        claimId = totalClaims;
        claims[claimId] = Claim({
            tokenId: tokenId,
            sourceCommit: sourceCommit,
            traceHash: traceHash,
            ipfsCid: ipfsCid,
            issuer: msg.sender,
            issuedAt: uint64(block.timestamp),
            window: window,
            dropThresholdBps: dropThresholdBps,
            status: STATUS_OPEN,
            resolvedAt: 0
        });
        emit ClaimIssued(claimId, tokenId, sourceCommit, traceHash, ipfsCid, window, dropThresholdBps);
    }

    /// @notice Bond USDC for (backsClaim=true → token rugs) or against a claim.
    function stake(uint256 claimId, bool backsClaim, uint256 amount) external {
        if (amount == 0) revert ZeroAmount();
        if (claimId == 0 || claimId > totalClaims) revert NoSuchClaim(claimId);
        if (claims[claimId].status != STATUS_OPEN) revert NotOpen(claimId);
        if (!bondToken.transferFrom(msg.sender, address(this), amount)) revert TransferFailed();
        if (backsClaim) {
            bonds[claimId].forStake += amount;
            forOf[claimId][msg.sender] += amount;
        } else {
            bonds[claimId].againstStake += amount;
            againstOf[claimId][msg.sender] += amount;
        }
        emit Staked(claimId, msg.sender, backsClaim, amount);
    }

    /// @notice Resolver records the outcome: rugged=true → claim TRUE.
    function resolve(uint256 claimId, bool rugged) external onlyResolver {
        if (claimId == 0 || claimId > totalClaims) revert NoSuchClaim(claimId);
        Claim storage c = claims[claimId];
        if (c.status != STATUS_OPEN) revert AlreadyResolved(claimId);
        c.status = rugged ? STATUS_RUGGED : STATUS_SAFE;
        c.resolvedAt = uint64(block.timestamp);
        emit Resolved(claimId, c.status, c.resolvedAt);
    }

    /// @notice Winners withdraw their stake + a pro-rata share of the losing
    ///         pool. Losers receive nothing (slashed). Idempotent per staker.
    /// @dev Checks-effects-interactions: the withdrawn flag is set before the
    ///      token transfer. If the winning pool drew no stake, the losing pool
    ///      stays in the contract (sweepable by a future treasury function).
    function withdraw(uint256 claimId) external returns (uint256 payout) {
        if (claimId == 0 || claimId > totalClaims) revert NoSuchClaim(claimId);
        Claim storage c = claims[claimId];
        if (c.status == STATUS_OPEN) revert NotResolvedYet(claimId);
        if (withdrawnOf[claimId][msg.sender]) revert AlreadyWithdrawn(claimId);
        withdrawnOf[claimId][msg.sender] = true;

        bool claimTrue = (c.status == STATUS_RUGGED);
        uint256 myWin = claimTrue ? forOf[claimId][msg.sender] : againstOf[claimId][msg.sender];
        if (myWin == 0) {
            emit Payout(claimId, msg.sender, 0);
            return 0;
        }
        Bond storage b = bonds[claimId];
        uint256 winPool = claimTrue ? b.forStake : b.againstStake;
        uint256 losePool = claimTrue ? b.againstStake : b.forStake;
        payout = myWin + (losePool == 0 ? 0 : (losePool * myWin) / winPool);
        if (!bondToken.transfer(msg.sender, payout)) revert TransferFailed();
        emit Payout(claimId, msg.sender, payout);
    }

    function getClaim(uint256 claimId) external view returns (Claim memory) {
        if (claimId == 0 || claimId > totalClaims) revert NoSuchClaim(claimId);
        return claims[claimId];
    }
}
