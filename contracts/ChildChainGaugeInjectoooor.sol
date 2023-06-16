// SPDX-License-Identifier: MIT

pragma solidity ^0.8.18;

import "@chainlink/contracts/src/v0.8/ConfirmedOwner.sol";
import "@chainlink/contracts/src/v0.8/interfaces/KeeperCompatibleInterface.sol";
import "@openzeppelin/contracts/security/Pausable.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "interfaces/balancer/IChildChainGauge.sol";


/**
 * @title The ChildChainGaugeInjector Contract
 * @author 0xtritium.eth + master coder Mike B
 * @notice This contract is a chainlink automation compatible interface to automate regular payment of non-BAL tokens to a child chain gauge.
 * @notice This contract is meant to run/manage a single token.  This is almost always the case for a DAO trying to use such a thing.
 * @notice The configuration is rewritten each time it is loaded.
 * @notice This contract will only function if it is configured as the distributor for a token/gauge it is operating on.
 * @notice The contract is meant to hold token balances, and works on a schedule set using setRecipientList.  The schedule defines an amount per round and number of rounds per gauge.
 * @notice This contract is Ownable and has lots of sweep functionality to allow the owner to work with the contract or get tokens out should there be a problem.
 * see https://docs.chain.link/chainlink-automation/utility-contracts/
 */


contract ChildChainGaugeInjector is ConfirmedOwner, Pausable, KeeperCompatibleInterface {
    event GasTokenWithdrawn(uint256 amountWithdrawn, address recipient);
    event KeeperRegistryAddressUpdated(address oldAddress, address newAddress);
    event MinWaitPeriodUpdated(uint256 oldMinWaitPeriod, uint256 newMinWaitPeriod);
    event ERC20Swept(address indexed token, address recipient, uint256 amount);
    event EmissionsInjection(address gauge, address token, uint256 amount);
    event SetHandlingToken(address token);
    event PerformedUpkeep(address[] needsFunding);


    error InvalidGaugeList(string message);
    error OnlyKeeperRegistry(address sender);
    error DuplicateAddress(address duplicate);
    error ZeroAddress();

    struct Target {
        uint256 amountPerPeriod;
        bool isActive;
        uint8 maxPeriods;
        uint8 periodNumber;
        uint56 lastInjectionTimeStamp; // enough space for 2 trillion years
    }


    address private s_keeperRegistryAddress;
    uint256 private s_minWaitPeriodSeconds;
    address[] private s_gaugeList;
    mapping(address => Target) internal s_targets;
    address private s_injectTokenAddress;

    /**
  * @param keeperRegistryAddress The address of the keeper registry contract
   * @param minWaitPeriodSeconds The minimum wait period for address between funding (for security)
   * @param injectTokenAddress The ERC20 token this contract should mange
   */
    constructor(address keeperRegistryAddress, uint256 minWaitPeriodSeconds, address injectTokenAddress)
    ConfirmedOwner(msg.sender)
    {
        setKeeperRegistryAddress(keeperRegistryAddress);
        setMinWaitPeriodSeconds(minWaitPeriodSeconds);
        setInjectTokenAddress(injectTokenAddress);
    }

    /**
     * @notice Sets the list of addresses to watch and their funding parameters
   * @param gaugeAddresses the list of addresses to watch
   * @param amountsPerPeriod the minimum balances for each address
   * @param maxPeriods the amount to top up each address
   */
    function setRecipientList(
        address[] calldata gaugeAddresses,
        uint256[] calldata amountsPerPeriod,
        uint8[] calldata maxPeriods
    ) public onlyOwner {
        if (gaugeAddresses.length != amountsPerPeriod.length || gaugeAddresses.length != maxPeriods.length) {
            revert InvalidGaugeList("supplied gauges are different lengths");
        }
        address[] memory oldGaugeList = s_gaugeList;
        for (uint256 idx = 0; idx < oldGaugeList.length; idx++) {
            s_targets[oldGaugeList[idx]].isActive = false;
        }
        revertOnDuplicate(gaugeAddresses);
        for (uint256 idx = 0; idx < gaugeAddresses.length; idx++) {

            if (gaugeAddresses[idx] == address(0)) {
                revert InvalidGaugeList("supplied gauge is 0 address");
            }
            if (amountsPerPeriod[idx] == 0) {
                revert InvalidGaugeList("amountPerPeriod cannot be 0");
            }
            s_targets[gaugeAddresses[idx]] = Target({
                isActive: true,
                amountPerPeriod: amountsPerPeriod[idx],
                maxPeriods: maxPeriods[idx],
                lastInjectionTimeStamp: 0,
                periodNumber: 0
            });
        }
        s_gaugeList = gaugeAddresses;
    }

    /**
     * @notice Validate that all periods are finished, and that the supplied schedule has the right amount of balance to execute on
     * @notice If everything checks out, update recipient list, otherwise, throw revert
     * @notice Note: this is griefable by someone transferring funds into the contract,
     * @notice you can use setRecipientList to set a list without validation
     * @param gaugeAddresses : list of gauge addresses
     * @param amountsPerPeriod : list of amount of token in wei to be injected each week
   */
    function setValidatedRecipientList(address[] calldata gaugeAddresses,
        uint256[] calldata amountsPerPeriod,
        uint8[] calldata maxPeriods
    ) external onlyOwner {
        address[] memory gaugeList = s_gaugeList;
        // validate all periods are finished
        for (uint256 idx = 0; idx < gaugeList.length; idx++) {
            Target memory target = s_targets[gaugeList[idx]];
            if (target.periodNumber < target.maxPeriods) {
                revert("periods not finished");
            }
        }
        setRecipientList(gaugeAddresses, amountsPerPeriod, maxPeriods);

        if (!checkExactBalancesMatch()) {
            revert("balance doesn't match for supplied schedules");
        }
    }

    /**
 * @notice Validate that the balances in the contract match the scheduled periods
     * @notice Used to make sure that balances match schedule
     * @notice note: this is griefable if others transfer tokens to the contract
   * @return bool true if balance of contract matches scheduled periods
   */
    function checkExactBalancesMatch() public view returns (bool){
        // iterates through all gauges to make sure theres enough tokens in the contract to fulfill all scheduled tasks
        // go through all gauges to see how many tokens are needed
        // maxperiods - periodnumber * amountPerPeriod ==  token.balanceOf(address(this))

        address[] memory gaugeList = s_gaugeList;
        uint256 totalDue;
        for (uint256 idx = 0; idx < gaugeList.length; idx++) {
            Target memory target = s_targets[gaugeList[idx]];
            totalDue += (target.maxPeriods - (target.periodNumber)) * target.amountPerPeriod;
        }
        return totalDue == IERC20(s_injectTokenAddress).balanceOf(address(this));
    }

    /**
     * @notice Gets a list of addresses that are ready to inject
     * @notice This is done by checking if the current period has ended, and should inject new funds directly after the end of each period.
   * @return list of addresses that are ready to inject
   */
    function getReadyGauges() public view returns (address[] memory) {
        address[] memory gaugeList = s_gaugeList;
        address[] memory ready = new address[](gaugeList.length);
        address tokenAddress = s_injectTokenAddress;
        uint256 count = 0;
        uint256 minWaitPeriod = s_minWaitPeriodSeconds;
        uint256 balance = IERC20(tokenAddress).balanceOf(address(this));
        Target memory target;
        for (uint256 idx = 0; idx < gaugeList.length; idx++) {
            target = s_targets[gaugeList[idx]];
            IChildChainGauge gauge = IChildChainGauge(gaugeList[idx]);

            uint256 period_finish = gauge.reward_data(tokenAddress).period_finish;

            if (
                target.lastInjectionTimeStamp + minWaitPeriod <= block.timestamp &&
                (period_finish <= block.timestamp) &&
                balance >= target.amountPerPeriod &&
                target.periodNumber < target.maxPeriods &&
                gauge.reward_data(tokenAddress).distributor == address(this)
            ) {
                ready[count] = gaugeList[idx];
                count++;
                balance -= target.amountPerPeriod;
            }
        }
        if (count != gaugeList.length) {
            // ready is a list large enough to hold all possible gauges
            // count is the number of ready gauges that were inserted into ready
            // this assembly shrinks ready to length count such that it removes empty elements
            assembly {
                mstore(ready, count)
            }
        }
        return ready;
    }

    /**
     * @notice Injects funds into the gauges provided
   * @param ready the list of gauges to fund (addresses must be pre-approved)
   */
    function _injectFunds(address[] memory ready) internal whenNotPaused {
        uint256 minWaitPeriodSeconds = s_minWaitPeriodSeconds;
        address tokenAddress = s_injectTokenAddress;
        IERC20 token = IERC20(tokenAddress);
        uint256 balance = token.balanceOf(address(this));
        Target memory target;

        for (uint256 idx = 0; idx < ready.length; idx++) {
            target = s_targets[ready[idx]];
            IChildChainGauge gauge = IChildChainGauge(ready[idx]);
            uint256 period_finish = gauge.reward_data(tokenAddress).period_finish;

            if (
                target.lastInjectionTimeStamp + s_minWaitPeriodSeconds <= block.timestamp &&
                period_finish <= block.timestamp &&
                balance >= target.amountPerPeriod &&
                target.periodNumber < target.maxPeriods &&
                target.isActive == true
            ) {

                SafeERC20.safeApprove(token, ready[idx], target.amountPerPeriod);

                try gauge.deposit_reward_token(address(token), uint256(target.amountPerPeriod)) {
                    s_targets[ready[idx]].lastInjectionTimeStamp = uint56(block.timestamp);
                    s_targets[ready[idx]].periodNumber += 1;
                    emit EmissionsInjection(ready[idx], address(token), target.amountPerPeriod);
                } catch {
                    revert("Failed to call deposit_reward_tokens");
                }
            }
        }
    }

    /**
 * * @notice This is to allow the owner to manually trigger an injection of funds in place of the keeper
   * @notice without abi encoding the gauge list
   * @param gauges array of gauges to inject tokens to
   */
    function injectFunds(address[] memory gauges) external onlyOwner {
        _injectFunds(gauges);
    }


    /**
     * @notice Get list of addresses that are ready for new token injections and return keeper-compatible payload
   * @param performData required by the chainlink interface but not used in this case.
   * @return upkeepNeeded signals if upkeep is needed
   * @return performData is an abi encoded list of addresses that need funds
   */
    function checkUpkeep(bytes calldata)
    external
    view
    override
    whenNotPaused
    returns (bool upkeepNeeded, bytes memory performData)
    {
        address[] memory ready = getReadyGauges();
        upkeepNeeded = ready.length > 0;
        performData = abi.encode(ready);
        return (upkeepNeeded, performData);
    }

    /**
     * @notice Called by keeper to send funds to underfunded addresses
   * @param performData The abi encoded list of addresses to fund
   */
    function performUpkeep(bytes calldata performData) external override onlyKeeperRegistry whenNotPaused {
        address[] memory needsFunding = abi.decode(performData, (address[]));
        _injectFunds(needsFunding);
        emit PerformedUpkeep(needsFunding);
    }

    /**
     * @notice Withdraws the contract balance
   */
    function withdrawGasToken() external onlyOwner {
        address payable recipient = payable(owner());
        if (recipient == address(0)) {
            revert ZeroAddress();
        }
        uint256 amount = address(this).balance;
        recipient.transfer(amount);
        emit GasTokenWithdrawn(amount, owner());
    }

    /**
     * @notice Sweep the full contract's balance for a given ERC-20 token
   * @param token The ERC-20 token which needs to be swept
   */
    function sweep(address token) external onlyOwner {
        uint256 balance = IERC20(token).balanceOf(address(this));
        SafeERC20.safeTransfer(IERC20(token), owner(), balance);
        emit ERC20Swept(token, owner(), balance);
    }



    /**
     * @notice Set distributor from the injector back to the owner.
     * @notice You will have to call set_reward_distributor back to the injector FROM the current distributor if you wish to continue using the injector
     * @notice be aware that the only addresses able to call set_reward_distributor are the current distributor and balancer governance authorized accounts (the LM multisig)
   * @param gauge The Gauge to set distributor for
   * @param reward_token Token you are setting the distributor for
   */
    function setDistributorToOwner(address gauge, address reward_token) external onlyOwner {
        IChildChainGauge gaugeContract = IChildChainGauge(gauge);
        gaugeContract.set_reward_distributor(reward_token, owner());
    }

    /**
   * @notice Manually deposit an amount of tokens to the gauge
   * @notice
   * @param gauge The Gauge to set distributor to injector owner
   * @param reward_token Reward token you are seeding
   * @param amount Amount to deposit
   */
    function manualDeposit(address gauge, address reward_token, uint256 amount) external onlyOwner {
        IChildChainGauge gaugeContract = IChildChainGauge(gauge);
        IERC20 token = IERC20(reward_token);
        SafeERC20.safeApprove(token, gauge, amount);
        gaugeContract.deposit_reward_token(reward_token, amount);
        emit EmissionsInjection(gauge, reward_token, amount);
    }

    /**
     * @notice Sets the keeper registry address
   */
    function setKeeperRegistryAddress(address keeperRegistryAddress) public onlyOwner {
        s_keeperRegistryAddress = keeperRegistryAddress;
        emit KeeperRegistryAddressUpdated(s_keeperRegistryAddress, keeperRegistryAddress);
    }

    /**
     * @notice Sets the minimum wait period (in seconds) for addresses between injections
   */
    function setMinWaitPeriodSeconds(uint256 period) public onlyOwner {
        s_minWaitPeriodSeconds = period;
        emit MinWaitPeriodUpdated(s_minWaitPeriodSeconds, period);
    }

    /**
     * @notice Gets the keeper registry address
   */
    function getKeeperRegistryAddress() external view returns (address keeperRegistryAddress) {
        return s_keeperRegistryAddress;
    }

    /**
     * @notice Gets the minimum wait period
   */
    function getMinWaitPeriodSeconds() external view returns (uint256) {
        return s_minWaitPeriodSeconds;
    }

    /**
     * @notice Gets the list of addresses on the in the current configuration.
   */
    function getWatchList() external view returns (address[] memory) {
        return s_gaugeList;
    }

    /**
     * @notice Sets the address of the ERC20 token this contract should handle
   */
    function setInjectTokenAddress(address ERC20token) public onlyOwner {
        s_injectTokenAddress = ERC20token;
        emit SetHandlingToken(ERC20token);
    }
    /**
     * @notice Gets the token this injector is operating on
   */
    function getInjectTokenAddress() external view returns (address){
        return s_injectTokenAddress;
    }
    /**
     * @notice Gets configuration information for an address on the gaugelist
     * @param targetAddress return Target struct for a given gauge according to the current scheduled distributions
   */
    function getAccountInfo(address targetAddress)
    external
    view
    returns (
        bool isActive,
        uint256 amountPerPeriod,
        uint8 maxPeriods,
        uint8 periodNumber,
        uint56 lastInjectionTimeStamp
    )
    {
        Target memory target = s_targets[targetAddress];
        return (target.isActive, target.amountPerPeriod, target.maxPeriods, target.periodNumber, target.lastInjectionTimeStamp);
    }

    /**
     * @notice Pauses the contract, which prevents executing performUpkeep
   */
    function pause() external onlyOwner {
        _pause();
    }

    /**
     * @notice Unpauses the contract
   */
    function unpause() external onlyOwner {
        _unpause();
    }

    /**
     * @notice takes in a list of addresses and reverts if there is a duplicate
   */
    function revertOnDuplicate(address[] memory list) internal pure {
        uint256 length = list.length;
        if(length == 0) {
           return;
        }
        for (uint256 i = 0; i < length - 1; i++) {
            for (uint256 j = i + 1; j < length; j++) {
                if (list[i] == list[j]) {
                    revert DuplicateAddress(list[i]);
                }
            }
        }
        // No duplicates found
    }

    modifier onlyKeeperRegistry() {
        if (msg.sender != s_keeperRegistryAddress) {
            revert OnlyKeeperRegistry(msg.sender);
        }
        _;
    }
}
