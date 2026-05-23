// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test, Vm} from "forge-std/Test.sol";
import {SusdeAcceptance} from "../src/SusdeAcceptance.sol";

contract SusdeAcceptanceTest is Test {
    SusdeAcceptance susde;

    // Mirror of the contract's typed-data constants so signatures verify.
    bytes32 constant CONSENT_TYPEHASH =
        keccak256("SusdeConsent(address user,uint64 version,bytes32 docHash,uint256 nonce)");
    bytes32 constant EIP712_DOMAIN_TYPEHASH =
        keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");

    function setUp() public {
        susde = new SusdeAcceptance();
    }

    /// @dev Rebuild the EIP-712 domain separator the same way the contract does.
    function _domainSeparator() internal view returns (bytes32) {
        return keccak256(
            abi.encode(
                EIP712_DOMAIN_TYPEHASH,
                keccak256(bytes("AKRITA SusdeAcceptance")),
                keccak256(bytes("1")),
                block.chainid,
                address(susde)
            )
        );
    }

    /// @dev Compute the final EIP-712 digest for a consent payload.
    function _digest(address user, uint64 version, bytes32 docHash, uint256 nonce)
        internal
        view
        returns (bytes32)
    {
        bytes32 structHash = keccak256(
            abi.encode(CONSENT_TYPEHASH, user, version, docHash, nonce)
        );
        return keccak256(abi.encodePacked("\x19\x01", _domainSeparator(), structHash));
    }

    /// @dev Sign a digest with a wallet and pack the 65-byte (r,s,v) signature.
    function _sign(Vm.Wallet memory wallet, bytes32 digest) internal pure returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(wallet, digest);
        return abi.encodePacked(r, s, v);
    }

    function test_accept_validSig_recordsAndEmits() public {
        Vm.Wallet memory user = vm.createWallet("user");
        uint64 version = 2;
        bytes32 docHash = keccak256("sUSDe cooldown terms v2");
        uint256 nonce = 0;

        bytes memory sig = _sign(user, _digest(user.addr, version, docHash, nonce));

        vm.expectEmit(true, true, false, true, address(susde));
        emit SusdeAccepted(user.addr, version, docHash, uint64(block.timestamp));

        // A relayer (not the user) submits the user's signature.
        vm.prank(address(0xCAFE));
        susde.accept(user.addr, version, docHash, nonce, sig);

        assertTrue(susde.hasAccepted(user.addr, version));
        assertEq(susde.nonces(user.addr), 1);

        SusdeAcceptance.Acceptance memory a = susde.acceptanceOf(user.addr);
        assertEq(a.version, version);
        assertEq(a.docHash, docHash);
        assertEq(a.acceptedAt, uint64(block.timestamp));
    }

    function test_accept_wrongSigner_reverts() public {
        Vm.Wallet memory user = vm.createWallet("user");
        Vm.Wallet memory attacker = vm.createWallet("attacker");
        uint64 version = 1;
        bytes32 docHash = keccak256("terms");
        uint256 nonce = 0;

        // Attacker signs a digest naming `user` as the consenter.
        bytes memory sig = _sign(attacker, _digest(user.addr, version, docHash, nonce));

        vm.expectRevert(SusdeAcceptance.InvalidSignature.selector);
        susde.accept(user.addr, version, docHash, nonce, sig);
    }

    function test_accept_replayNonce_reverts() public {
        Vm.Wallet memory user = vm.createWallet("user");
        uint64 version = 1;
        bytes32 docHash = keccak256("terms");
        uint256 nonce = 0;

        bytes memory sig = _sign(user, _digest(user.addr, version, docHash, nonce));

        susde.accept(user.addr, version, docHash, nonce, sig);

        // Replaying the same signature/nonce must fail: nonce is now 1.
        vm.expectRevert(abi.encodeWithSelector(SusdeAcceptance.BadNonce.selector, 1, 0));
        susde.accept(user.addr, version, docHash, nonce, sig);
    }

    function test_hasAccepted_falseBeforeTrueAfter() public {
        Vm.Wallet memory user = vm.createWallet("user");
        uint64 version = 1;
        bytes32 docHash = keccak256("terms");

        assertFalse(susde.hasAccepted(user.addr, version));

        bytes memory sig = _sign(user, _digest(user.addr, version, docHash, 0));
        susde.accept(user.addr, version, docHash, 0, sig);

        assertTrue(susde.hasAccepted(user.addr, version));
    }

    function test_staleVersion_notAccepted() public {
        Vm.Wallet memory user = vm.createWallet("user");
        uint64 version = 2;
        bytes32 docHash = keccak256("terms v2");

        bytes memory sig = _sign(user, _digest(user.addr, version, docHash, 0));
        susde.accept(user.addr, version, docHash, 0, sig);

        // Accepted at v2: a request for a newer v3 is not satisfied,
        // but an older v1 requirement is.
        assertFalse(susde.hasAccepted(user.addr, 3));
        assertTrue(susde.hasAccepted(user.addr, 1));
        assertTrue(susde.hasAccepted(user.addr, 2));
    }

    // Local declaration so vm.expectEmit can match the contract event.
    event SusdeAccepted(
        address indexed user,
        uint64 indexed version,
        bytes32 docHash,
        uint64 timestamp
    );
}
