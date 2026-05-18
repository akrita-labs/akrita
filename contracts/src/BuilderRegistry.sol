// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title BuilderRegistry
/// @notice Maps AKRITA agents to their Polymarket V2 builder codes and
///         tracks ERC-8004 reputation scores.
contract BuilderRegistry {
    struct Agent {
        bytes32 builderCode;        // Polymarket V2 bytes32 attribution
        address controllerWallet;   // Circle Developer-Controlled Wallet
        uint64  reputation;         // ERC-8004 score, 0..10000
        uint64  registeredAt;
        bool    active;
    }

    address public owner;
    address public reputationOracle;

    mapping(uint256 => Agent) public agents;          // agentId -> Agent
    mapping(bytes32 => uint256) public byBuilderCode; // builderCode -> agentId

    event AgentRegistered(uint256 indexed agentId, bytes32 indexed builderCode, address controllerWallet);
    event ReputationUpdated(uint256 indexed agentId, uint64 oldScore, uint64 newScore);
    event AgentDeactivated(uint256 indexed agentId);

    error NotOwner(address caller);
    error NotReputationOracle(address caller);
    error AlreadyRegistered(uint256 agentId);
    error InvalidScore(uint64 score);

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner(msg.sender);
        _;
    }

    modifier onlyReputationOracle() {
        if (msg.sender != reputationOracle) revert NotReputationOracle(msg.sender);
        _;
    }

    constructor() {
        owner = msg.sender;
        reputationOracle = msg.sender;
    }

    function setReputationOracle(address newOracle) external onlyOwner {
        reputationOracle = newOracle;
    }

    function registerAgent(
        uint256 agentId,
        bytes32 builderCode,
        address controllerWallet
    ) external onlyOwner {
        if (agents[agentId].registeredAt != 0) revert AlreadyRegistered(agentId);

        agents[agentId] = Agent({
            builderCode: builderCode,
            controllerWallet: controllerWallet,
            reputation: 5000,                // start at midpoint
            registeredAt: uint64(block.timestamp),
            active: true
        });
        byBuilderCode[builderCode] = agentId;

        emit AgentRegistered(agentId, builderCode, controllerWallet);
    }

    function updateReputation(uint256 agentId, uint64 newScore) external onlyReputationOracle {
        if (newScore > 10000) revert InvalidScore(newScore);
        uint64 old = agents[agentId].reputation;
        agents[agentId].reputation = newScore;
        emit ReputationUpdated(agentId, old, newScore);
    }

    function deactivate(uint256 agentId) external onlyOwner {
        agents[agentId].active = false;
        emit AgentDeactivated(agentId);
    }

    function isActive(uint256 agentId) external view returns (bool) {
        return agents[agentId].active;
    }

    function getBuilderCode(uint256 agentId) external view returns (bytes32) {
        return agents[agentId].builderCode;
    }
}
