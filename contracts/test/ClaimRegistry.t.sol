// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import {ClaimRegistry} from "../src/ClaimRegistry.sol";

/// Minimal 6-decimal mock token standing in for USDC on Arc.
contract MockUSDC {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 amt) external {
        balanceOf[to] += amt;
    }

    function approve(address spender, uint256 amt) external returns (bool) {
        allowance[msg.sender][spender] = amt;
        return true;
    }

    function transfer(address to, uint256 amt) external returns (bool) {
        balanceOf[msg.sender] -= amt;
        balanceOf[to] += amt;
        return true;
    }

    function transferFrom(address from, address to, uint256 amt) external returns (bool) {
        allowance[from][msg.sender] -= amt;
        balanceOf[from] -= amt;
        balanceOf[to] += amt;
        return true;
    }
}

contract ClaimRegistryTest is Test {
    ClaimRegistry reg;
    MockUSDC usdc;

    address alice = address(0xA11CE);
    address bob = address(0xB0B);

    function setUp() public {
        usdc = new MockUSDC();
        reg = new ClaimRegistry(address(usdc)); // deployer = issuer + resolver
        usdc.mint(alice, 1_000e6);
        usdc.mint(bob, 1_000e6);
    }

    function _issue() internal returns (uint256) {
        return reg.issueClaim(
            keccak256("PEPE/USDT@hyperliquid"),
            keccak256("nfi-commit-sha"),
            keccak256("trace-body"),
            "bafytrace",
            7 days,
            5000
        );
    }

    function test_issue_and_get() public {
        uint256 id = _issue();
        assertEq(id, 1);
        ClaimRegistry.Claim memory c = reg.getClaim(id);
        assertEq(c.dropThresholdBps, 5000);
        assertEq(uint256(c.status), 0);
        assertEq(c.window, 7 days);
    }

    function test_issue_onlyIssuer() public {
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(ClaimRegistry.NotIssuer.selector, alice));
        reg.issueClaim(bytes32(0), bytes32(0), bytes32(0), "x", 1 days, 100);
    }

    function test_stake_resolve_withdraw_payout() public {
        uint256 id = _issue();

        vm.startPrank(alice); // backs the claim (rug)
        usdc.approve(address(reg), 100e6);
        reg.stake(id, true, 100e6);
        vm.stopPrank();

        vm.startPrank(bob); // against (token holds)
        usdc.approve(address(reg), 100e6);
        reg.stake(id, false, 100e6);
        vm.stopPrank();

        reg.resolve(id, true); // rugged → alice's side wins, bob slashed

        vm.prank(alice);
        uint256 pay = reg.withdraw(id);
        assertEq(pay, 200e6); // 100 stake back + 100 from the losing pool
        assertEq(usdc.balanceOf(alice), 1_000e6 + 100e6); // net +100

        vm.prank(bob);
        assertEq(reg.withdraw(id), 0); // loser slashed
        assertEq(usdc.balanceOf(bob), 1_000e6 - 100e6); // net -100

        vm.prank(alice); // idempotent
        vm.expectRevert(abi.encodeWithSelector(ClaimRegistry.AlreadyWithdrawn.selector, id));
        reg.withdraw(id);
    }

    function test_resolve_onlyResolver() public {
        uint256 id = _issue();
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(ClaimRegistry.NotResolver.selector, alice));
        reg.resolve(id, true);
    }

    function test_withdraw_before_resolve_reverts() public {
        uint256 id = _issue();
        vm.startPrank(alice);
        usdc.approve(address(reg), 50e6);
        reg.stake(id, true, 50e6);
        vm.stopPrank();
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(ClaimRegistry.NotResolvedYet.selector, id));
        reg.withdraw(id);
    }

    function test_stake_on_resolved_reverts() public {
        uint256 id = _issue();
        reg.resolve(id, false);
        vm.startPrank(alice);
        usdc.approve(address(reg), 10e6);
        vm.expectRevert(abi.encodeWithSelector(ClaimRegistry.NotOpen.selector, id));
        reg.stake(id, true, 10e6);
        vm.stopPrank();
    }

    function test_one_sided_winner_gets_stake_back() public {
        uint256 id = _issue();
        vm.startPrank(alice);
        usdc.approve(address(reg), 75e6);
        reg.stake(id, true, 75e6);
        vm.stopPrank();
        reg.resolve(id, true); // only "for" stake exists, and it wins
        vm.prank(alice);
        assertEq(reg.withdraw(id), 75e6); // no losing pool → just stake back
    }
}
