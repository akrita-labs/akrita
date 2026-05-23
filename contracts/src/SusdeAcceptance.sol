// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title SusdeAcceptance
/// @notice EIP-712 consent registry for AGROS Tier C sUSDe cooldown acceptance.
/// @dev Self-sovereign, append-only record of a user's signed acknowledgement
///      that they understand the sUSDe (Ethena staked USDe) cooldown/unstaking
///      terms before AGROS allocates Tier C capital on their behalf. The user
///      signs the typed data off-chain; a relayer/keeper may submit the
///      signature on-chain (meta-transaction style) so the user pays no gas.
///      EIP-712 is implemented manually (keccak256/abi.encode + ecrecover) to
///      keep the contract dependency-light, matching the rest of the repo.
contract SusdeAcceptance {
    struct Acceptance {
        uint64  version;     // policy/doc version the user consented to
        uint64  acceptedAt;  // block timestamp of acceptance (0 == never)
        bytes32 docHash;     // sha256/keccak of the consent document body
    }

    /// @dev EIP-712 typed-data struct hash for the consent payload.
    ///      SusdeConsent(address user,uint64 version,bytes32 docHash,uint256 nonce)
    bytes32 public constant CONSENT_TYPEHASH =
        keccak256("SusdeConsent(address user,uint64 version,bytes32 docHash,uint256 nonce)");

    /// @dev EIP-712 domain typehash (name, version, chainId, verifyingContract).
    bytes32 private constant EIP712_DOMAIN_TYPEHASH =
        keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");

    bytes32 private constant NAME_HASH = keccak256(bytes("AKRITA SusdeAcceptance"));
    bytes32 private constant VERSION_HASH = keccak256(bytes("1"));

    /// @dev Domain separator components captured at deploy time so we can
    ///      rebuild the separator if the chain forks (chainId changes).
    uint256 private immutable _CACHED_CHAIN_ID;
    bytes32 private immutable _CACHED_DOMAIN_SEPARATOR;

    mapping(address => Acceptance) public acceptances;
    mapping(address => uint256) public nonces;

    event SusdeAccepted(
        address indexed user,
        uint64 indexed version,
        bytes32 docHash,
        uint64 timestamp
    );

    error InvalidSignature();
    error BadNonce(uint256 expected, uint256 got);

    constructor() {
        _CACHED_CHAIN_ID = block.chainid;
        _CACHED_DOMAIN_SEPARATOR = _buildDomainSeparator();
    }

    /// @notice Record a user's signed sUSDe cooldown consent.
    /// @dev The signature must be produced by `user` over the EIP-712 typed
    ///      data. Anyone (typically a relayer/keeper) may submit it. The nonce
    ///      must equal the user's current nonce, which is then incremented to
    ///      prevent replay.
    function accept(
        address user,
        uint64 version,
        bytes32 docHash,
        uint256 nonce,
        bytes calldata sig
    ) external {
        uint256 expected = nonces[user];
        if (nonce != expected) revert BadNonce(expected, nonce);

        bytes32 structHash = keccak256(
            abi.encode(CONSENT_TYPEHASH, user, version, docHash, nonce)
        );
        bytes32 digest = keccak256(
            abi.encodePacked("\x19\x01", DOMAIN_SEPARATOR(), structHash)
        );

        address signer = _recover(digest, sig);
        if (signer == address(0) || signer != user) revert InvalidSignature();

        nonces[user] = expected + 1;
        acceptances[user] = Acceptance({
            version: version,
            acceptedAt: uint64(block.timestamp),
            docHash: docHash
        });

        emit SusdeAccepted(user, version, docHash, uint64(block.timestamp));
    }

    /// @notice True if the user has accepted at least the given version.
    function hasAccepted(address user, uint64 version) external view returns (bool) {
        Acceptance storage a = acceptances[user];
        return a.acceptedAt != 0 && a.version >= version;
    }

    /// @notice Full acceptance record for a user.
    function acceptanceOf(address user) external view returns (Acceptance memory) {
        return acceptances[user];
    }

    /// @notice EIP-712 domain separator, rebuilt if the chainId has changed.
    function DOMAIN_SEPARATOR() public view returns (bytes32) {
        if (block.chainid == _CACHED_CHAIN_ID) {
            return _CACHED_DOMAIN_SEPARATOR;
        }
        return _buildDomainSeparator();
    }

    function _buildDomainSeparator() private view returns (bytes32) {
        return keccak256(
            abi.encode(
                EIP712_DOMAIN_TYPEHASH,
                NAME_HASH,
                VERSION_HASH,
                block.chainid,
                address(this)
            )
        );
    }

    /// @dev ecrecover a 65-byte (r,s,v) signature; rejects malformed lengths
    ///      and the high-s malleability range.
    function _recover(bytes32 digest, bytes calldata sig) private pure returns (address) {
        if (sig.length != 65) return address(0);

        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := calldataload(sig.offset)
            s := calldataload(add(sig.offset, 0x20))
            v := byte(0, calldataload(add(sig.offset, 0x40)))
        }

        // Reject high-s values to enforce signature non-malleability (EIP-2).
        if (uint256(s) > 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0) {
            return address(0);
        }
        if (v != 27 && v != 28) return address(0);

        return ecrecover(digest, v, r, s);
    }
}
