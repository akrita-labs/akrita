// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title TraceRegistry
/// @notice Append-only log of AKRITA agent decision hashes + IPFS CIDs.
/// @dev Each call to commitTrace stores one (agent, decision_id, hash, cid)
///      tuple and emits an event. The body itself lives on IPFS (pinned via
///      Circle Nanopayments); only the integrity hash and CID are stored
///      on-chain, bounding the on-chain footprint.
contract TraceRegistry {
    struct Commit {
        uint256 agentId;       // NOMOS=1, SPATHA=2, AGROS=3 (see BuilderRegistry)
        uint256 decisionId;    // monotonic per agent
        bytes32 traceHash;     // sha256(canonical_json(trace_body))
        string  ipfsCid;       // CIDv1 base32
        uint64  timestamp;
    }

    address public owner;
    mapping(uint256 => Commit) public commits;
    mapping(uint256 => mapping(uint256 => uint256)) public byAgentDecision;
    mapping(address => bool) public authorizedKeepers;
    uint256 public totalCommits;

    event TraceCommitted(
        uint256 indexed agentId,
        uint256 indexed decisionId,
        bytes32 traceHash,
        string ipfsCid,
        uint64 timestamp
    );
    event KeeperAuthorized(address indexed keeper, bool authorized);

    error DuplicateDecision(uint256 agentId, uint256 decisionId);
    error NotAuthorized(address caller);
    error NotOwner(address caller);

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner(msg.sender);
        _;
    }

    modifier onlyAuthorized() {
        if (!authorizedKeepers[msg.sender]) revert NotAuthorized(msg.sender);
        _;
    }

    constructor() {
        owner = msg.sender;
        authorizedKeepers[msg.sender] = true;
    }

    function setKeeper(address keeper, bool authorized) external onlyOwner {
        authorizedKeepers[keeper] = authorized;
        emit KeeperAuthorized(keeper, authorized);
    }

    /// @notice Commit a trace hash + IPFS CID for an agent decision.
    /// @dev Reverts if the (agentId, decisionId) pair has already been committed.
    function commitTrace(
        uint256 agentId,
        uint256 decisionId,
        bytes32 traceHash,
        string calldata ipfsCid
    ) external onlyAuthorized returns (uint256 commitIndex) {
        if (byAgentDecision[agentId][decisionId] != 0) {
            revert DuplicateDecision(agentId, decisionId);
        }

        totalCommits += 1;
        commitIndex = totalCommits;
        commits[commitIndex] = Commit({
            agentId: agentId,
            decisionId: decisionId,
            traceHash: traceHash,
            ipfsCid: ipfsCid,
            timestamp: uint64(block.timestamp)
        });
        byAgentDecision[agentId][decisionId] = commitIndex;

        emit TraceCommitted(agentId, decisionId, traceHash, ipfsCid, uint64(block.timestamp));
    }

    /// @notice Verify that a given trace body matches the on-chain commit.
    /// @param agentId The agent that produced the decision.
    /// @param decisionId The decision counter.
    /// @param traceBody The canonical-JSON-encoded reasoning trace body.
    /// @return ok True if sha256(traceBody) == stored traceHash.
    function verifyTrace(
        uint256 agentId,
        uint256 decisionId,
        bytes calldata traceBody
    ) external view returns (bool ok) {
        uint256 idx = byAgentDecision[agentId][decisionId];
        if (idx == 0) return false;
        return sha256(traceBody) == commits[idx].traceHash;
    }

    function getCommit(uint256 agentId, uint256 decisionId)
        external
        view
        returns (Commit memory)
    {
        uint256 idx = byAgentDecision[agentId][decisionId];
        require(idx != 0, "TraceRegistry: not found");
        return commits[idx];
    }
}
