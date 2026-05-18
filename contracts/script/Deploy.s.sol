// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console2} from "forge-std/Script.sol";
import {TraceRegistry} from "../src/TraceRegistry.sol";
import {BuilderRegistry} from "../src/BuilderRegistry.sol";

/// @notice Deploy AKRITA contracts to Arc testnet.
/// Run with:
///   forge script script/Deploy.s.sol --rpc-url $ARC_RPC --broadcast
contract DeployScript is Script {
    function run() external {
        uint256 deployerKey = vm.envUint("PRIVATE_KEY");
        vm.startBroadcast(deployerKey);

        TraceRegistry traceReg = new TraceRegistry();
        console2.log("TraceRegistry:", address(traceReg));

        BuilderRegistry builderReg = new BuilderRegistry();
        console2.log("BuilderRegistry:", address(builderReg));

        // Pre-register the three AKRITA agents
        bytes32 nomosCode = vm.envBytes32("NOMOS_BUILDER_CODE");
        builderReg.registerAgent(1, nomosCode, vm.envAddress("NOMOS_WALLET"));

        // SPATHA and AGROS don't quote Polymarket directly; they get null builder codes
        builderReg.registerAgent(2, bytes32(0), vm.envAddress("SPATHA_WALLET"));
        builderReg.registerAgent(3, bytes32(0), vm.envAddress("AGROS_WALLET"));

        // Authorize the trace keeper to commit to TraceRegistry
        traceReg.setKeeper(vm.envAddress("TRACE_KEEPER_WALLET"), true);

        vm.stopBroadcast();
    }
}
