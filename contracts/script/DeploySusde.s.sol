// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console2} from "forge-std/Script.sol";
import {SusdeAcceptance} from "../src/SusdeAcceptance.sol";

/// @notice Deploy the SusdeAcceptance consent registry to Arc testnet.
/// Run with:
///   forge script script/DeploySusde.s.sol --rpc-url $ARC_RPC --broadcast
/// Requires env: PRIVATE_KEY (deployer key, hex with 0x prefix).
contract DeploySusdeScript is Script {
    function run() external {
        uint256 deployerKey = vm.envUint("PRIVATE_KEY");
        vm.startBroadcast(deployerKey);

        SusdeAcceptance susde = new SusdeAcceptance();
        console2.log("SusdeAcceptance:", address(susde));
        console2.logBytes32(susde.DOMAIN_SEPARATOR());

        vm.stopBroadcast();
    }
}
