//SPDX-License-Identifier: Unlicense
pragma solidity ^0.8.18;

import "./ChildChainGaugeInjectoooor.sol";

contract injectorFactory {
    ChildChainGaugeInjector[] public InjectorArray;

    event injectorCreated(address injector, address tokenAddress, address owner);

    function createNewInjector(address keeperRegistryAddress, uint256 minWaitPeriodSeconds, address injectTokenAddress, address _owner) public returns(ChildChainGaugeInjector) {
        ChildChainGaugeInjector injector = new ChildChainGaugeInjector(keeperRegistryAddress, minWaitPeriodSeconds, injectTokenAddress);
        InjectorArray.push(injector);
        injector.transferOwnership(_owner);
        emit injectorCreated(address(injector), injector.getInjectTokenAddress(), injector.owner());
        return injector;

    }

}