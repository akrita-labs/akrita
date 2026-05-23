// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {TraceRegistry} from "../src/TraceRegistry.sol";

contract TraceRegistryTest is Test {
    TraceRegistry registry;
    address keeper = address(0xBEEF);

    function setUp() public {
        registry = new TraceRegistry();
        registry.setKeeper(keeper, true);
    }

    function test_commitTrace_emitsEvent() public {
        bytes32 hash = keccak256("trace body 1");
        string memory cid = "bafytest1";

        vm.prank(keeper);
        uint256 idx = registry.commitTrace(1, 42, hash, cid);

        assertEq(idx, 1);
        assertEq(registry.totalCommits(), 1);
    }

    function test_commitTrace_duplicateReverts() public {
        bytes32 hash = keccak256("trace");
        string memory cid = "bafytest";

        vm.startPrank(keeper);
        registry.commitTrace(1, 42, hash, cid);

        vm.expectRevert(abi.encodeWithSelector(
            TraceRegistry.DuplicateDecision.selector, 1, 42
        ));
        registry.commitTrace(1, 42, hash, cid);
        vm.stopPrank();
    }

    function test_commitTrace_unauthorizedReverts() public {
        // The test contract deploys the registry, so it is auto-authorized as
        // the deployer. Prank from a stranger to exercise the unauthorized path.
        address stranger = address(0xDEAD);
        bytes32 hash = keccak256("trace");
        vm.prank(stranger);
        vm.expectRevert(abi.encodeWithSelector(
            TraceRegistry.NotAuthorized.selector, stranger
        ));
        registry.commitTrace(1, 42, hash, "bafy");
    }

    function test_verifyTrace_matches() public {
        bytes memory body = abi.encode("test reasoning trace");
        bytes32 hash = sha256(body);

        vm.prank(keeper);
        registry.commitTrace(1, 7, hash, "bafy7");

        assertTrue(registry.verifyTrace(1, 7, body));
        assertFalse(registry.verifyTrace(1, 7, abi.encode("different body")));
    }

    function test_verifyTrace_missingReturnsFalse() public {
        assertFalse(registry.verifyTrace(1, 999, abi.encode("any")));
    }
}
