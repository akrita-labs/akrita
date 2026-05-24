// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console2} from "forge-std/Script.sol";
import {ClaimRegistry} from "../src/ClaimRegistry.sol";

/// @notice Deploy the AKRITA Rugpull Oracle ClaimRegistry to Arc testnet.
/// Run with:
///   forge script script/DeployClaimRegistry.s.sol --rpc-url $ARC_RPC --broadcast
/// Env:
///   PRIVATE_KEY     deployer (becomes owner + first issuer + first resolver)
///   BOND_TOKEN      USDC on Arc (defaults to the native USDC precompile addr)
///   CLAIM_ISSUER    optional NOMOS claim-issuing keeper to authorize
///   CLAIM_RESOLVER  optional resolver keeper to authorize
contract DeployClaimRegistry is Script {
    address constant DEFAULT_USDC = 0x3600000000000000000000000000000000000000;

    function run() external {
        uint256 deployerKey = vm.envUint("PRIVATE_KEY");
        address bondToken = vm.envOr("BOND_TOKEN", DEFAULT_USDC);

        vm.startBroadcast(deployerKey);

        ClaimRegistry reg = new ClaimRegistry(bondToken);
        console2.log("ClaimRegistry:", address(reg));
        console2.log("bondToken:", bondToken);

        address issuer = vm.envOr("CLAIM_ISSUER", address(0));
        if (issuer != address(0)) {
            reg.setIssuer(issuer, true);
            console2.log("authorized issuer:", issuer);
        }
        address resolver = vm.envOr("CLAIM_RESOLVER", address(0));
        if (resolver != address(0)) {
            reg.setResolver(resolver, true);
            console2.log("authorized resolver:", resolver);
        }

        vm.stopBroadcast();
    }
}
