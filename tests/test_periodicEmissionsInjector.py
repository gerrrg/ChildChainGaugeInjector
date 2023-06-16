import brownie
import time
from brownie import chain, Contract
import pytest
import random


ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

def test_deploy(deploy):
    return

def test_set_recipient_list(injector, admin, gauge):
    recipients = [gauge]
    amounts = [100]
    periods = [3]
    injector.setRecipientList(recipients, amounts, periods, {"from": admin})
    assert injector.getWatchList() == recipients
    assert injector.getAccountInfo(recipients[0]) == (True, 100, 3, 0, 0)


def test_can_call_check_upkeep(upkeep_caller, injector, gauge, admin):
    # Arrange
    injector.setRecipientList([gauge.address], [100], [2], {"from": admin})
    upkeepNeeded, performData = injector.checkUpkeep.call(
        "",
        {"from": upkeep_caller},
    )
    assert isinstance(upkeepNeeded, bool)
    assert isinstance(performData, bytes)


def test_integration_perform_upkeep_flows(injector, upkeep_caller, token, admin, whale, gauge,weekly_incentive):
    ## Setup [2] for 2 rounds

    assert token.balanceOf(injector.address) == 0
    token.transfer(injector, weekly_incentive*3, {"from": admin}) # Tokens for 3 rounds so we are stopped by max rounds in the injector config
    injector.setRecipientList([gauge.address], [weekly_incentive], [2], {"from": admin})
    reward_data = gauge.reward_data(token)
## Advance to the next Epoch
    (upkeepNeeded, performData) = injector.checkUpkeep("", {"from": upkeep_caller})
    if upkeepNeeded is False:
        sleep_time = (reward_data[1] - chain.time())  # about 1 block after the peroiod ends.
        chain.sleep(sleep_time)
        chain.mine()
        ## Test perform upkeep for the first round
        (upkeepNeeded, performData) = injector.checkUpkeep(
            "",
            {"from": upkeep_caller},
        )
        assert(upkeepNeeded is True)

    initial_gauge_balance = token.balanceOf(gauge)

    assert(token.balanceOf(injector) >= weekly_incentive)  # injector should have coinz
    assert(injector.performUpkeep(performData, {"from": upkeep_caller})) # Perform upkeep
    ### Check that we did something and at best that its right
    assert (token.balanceOf(gauge) == initial_gauge_balance + weekly_incentive)
    ## advance time and check that claim reduces streamer balancer
    (upkeepNeeded, performData) = injector.checkUpkeep("", {"from": upkeep_caller})
    assert(upkeepNeeded==False)  ## not time yet
    r1_gauge_balance = token.balanceOf(gauge)
    chain.mine()
    chain.sleep(300)
    chain.mine()
    (upkeepNeeded, performData) = injector.checkUpkeep("",{"from": ZERO_ADDRESS})
    assert(upkeepNeeded == False) # not time yet
    claim = gauge.claim_rewards({"from": whale})
    assert(token.balanceOf(gauge) < r1_gauge_balance)  # Whale pulled tokens from streamer on claim

    # sleep till second epoch
    chain.sleep(60*60*24*8) # 8 days should be more than a 1 week epoch
    chain.mine()
    (upkeepNeeded, performData) = injector.checkUpkeep("",{"from": ZERO_ADDRESS})
    assert(upkeepNeeded == True)
    # Test second upkeep
    initial_system_balance  =  token.balanceOf(gauge)
    assert(injector.performUpkeep(performData, {"from": upkeep_caller})) # Perform upkeep
    assert ( token.balanceOf(gauge) - initial_system_balance == weekly_incentive)  # injector should have new coinz
    (upkeepNeeded, performData) = injector.checkUpkeep("", {"from": ZERO_ADDRESS})
    assert (upkeepNeeded == False)  # not time yet

    #check third epcoh we stop
    chain.sleep(60 * 60 * 24 * 8)  # 8 days should be more than a 1 week epoch
    chain.mine()
    (upkeepNeeded, performData) = injector.checkUpkeep("", {"from": ZERO_ADDRESS})
    assert (upkeepNeeded == False)  # No more runs



def test_pause_and_unpause(injector, admin, upkeep_caller):
    # Pause the contract
    injector.pause({"from": admin})
    assert injector.paused({"from": admin}) is True

    # Wait for the minimum wait period and trigger injection (should fail due to pause)
    chain.sleep(injector.getMinWaitPeriodSeconds())
    with brownie.reverts("Pausable: paused"):
        injector.checkUpkeep("")

    # Unpause the contract
    injector.unpause({"from": admin})
    assert injector.paused({"from": admin}) is False


def test_wont_run_to_soon(injector, upkeep_caller, token, gauge, weekly_incentive, admin):
    ## Advance to beginning of the next epoch
    injector.setRecipientList([gauge.address], [weekly_incentive], [2], {"from": admin})
    token.transfer(injector, weekly_incentive*2, {"from": admin})
    reward_data = gauge.reward_data(token)
    (upkeepNeeded, performData) = injector.checkUpkeep("", {"from": upkeep_caller})
    if upkeepNeeded is False:
        sleep_time = (reward_data[1] - chain.time())  # about 1 block after the peroiod ends.
        chain.sleep(sleep_time)
        chain.mine()
        (upkeepNeeded, performData) = injector.checkUpkeep(
            "",
            {"from": upkeep_caller},
        )
        assert(upkeepNeeded is True)
    ## Test perform upkeep for the first round
    initial_gauge_balance = token.balanceOf(gauge)
    assert(token.balanceOf(injector) >= weekly_incentive)  # injector should have coinz
    assert(injector.performUpkeep(performData, {"from": upkeep_caller})) # Perform upkeep
    ## Start test
    (upkeepNeeded, performData) = injector.checkUpkeep("", {"from": upkeep_caller})
    reward_data = gauge.reward_data(token)
    (distributor, period_finished, rate, last_update, integral) = reward_data
    sleep_time = random.randint(1, 60*60*24*6)
    chain.sleep(sleep_time)
    chain.mine()
    (upkeepNeeded, performData) = injector.checkUpkeep("", {"from": upkeep_caller})
    assert not upkeepNeeded
    (distributor, period_finished, rate, last_update, integral) = reward_data
    sleep_time = (period_finished+1) - chain.time()
    chain.sleep(sleep_time)
    chain.mine()
    (upkeepNeeded, performData) = injector.checkUpkeep("", {"from": upkeep_caller})
    assert upkeepNeeded


def test_long_upkeep_delay(token, injector, upkeep_caller, weekly_incentive, gauge, admin, whale):

    injector.setRecipientList([gauge.address], [weekly_incentive], [2], {"from": admin})
    token.transfer(injector, 1000*10**18*2, {"from": admin})
    reward_data = gauge.reward_data(token)
    ## Advance to the next Epoch
    (upkeepNeeded, performData) = injector.checkUpkeep("", {"from": upkeep_caller})
    if upkeepNeeded is False:
        sleep_time = (reward_data[1] - chain.time())  # about 1 block after the peroiod ends.
        chain.sleep(sleep_time)
        chain.mine()
        (upkeepNeeded, performData) = injector.checkUpkeep(
            "",
            {"from": upkeep_caller},
        )
        assert (upkeepNeeded is True)
    assert (token.balanceOf(injector) >= weekly_incentive)  # injector should have coinz
    chain.sleep(random.randint(60*60*4, 60*60*24*365))  # random sleep between 4 hours and 1 year
    chain.mine()
    assert (injector.performUpkeep(performData, {"from": upkeep_caller}))  # Perform upkeep
    ## advance time and check that claim reduces streamer balancer
    (upkeepNeeded, performData) = injector.checkUpkeep("", {"from": upkeep_caller})
    assert (upkeepNeeded == False)  ## not time yet
    r1_gauge_balance = token.balanceOf(gauge)
    chain.mine()
    chain.sleep(300)
    chain.mine()
    (upkeepNeeded, performData) = injector.checkUpkeep("", {"from": ZERO_ADDRESS})
    assert (upkeepNeeded == False)  # not time yet
    claim = gauge.claim_rewards({"from": whale})
    assert (token.balanceOf(gauge) < r1_gauge_balance)  # Whale pulled tokens from streamer on claim

def test_too_short_upkeep_delay(injector, upkeep_caller, token, weekly_incentive, gauge, admin):
    injector.setRecipientList([gauge.address], [weekly_incentive], [2], {"from": admin})
    token.transfer(injector, 1000*10**18*2, {"from": admin})
    reward_data = gauge.reward_data(token)
    ## Advance to the next Epoch
    (upkeepNeeded, performData) = injector.checkUpkeep("", {"from": upkeep_caller})
    if upkeepNeeded is False:
        sleep_time = (reward_data[1] - chain.time())  # about 1 block after the period ends.
        chain.sleep(sleep_time)
        chain.mine()
        (upkeepNeeded, performData) = injector.checkUpkeep(
            "",
            {"from": upkeep_caller},
        )
        assert (upkeepNeeded is True)
    ## Test perform upkeep for the first round
    initial_gauge_balance = token.balanceOf(gauge)
    assert (token.balanceOf(injector) >= weekly_incentive)  # injector should have coinz
    assert (injector.performUpkeep(performData, {"from": upkeep_caller}))  # Perform upkeep
    chain.sleep(random.randint(1, 60*60*24*7 - 1)) # Between 1 second and 1 second less than 1 week
    (upkeepNeeded, performData) = injector.checkUpkeep("", {"from": upkeep_caller})
    assert upkeepNeeded is False


def test_sweep(admin, injector, token, deployer):
    system_balance = token.balanceOf(admin) + token.balanceOf(injector)
    admin_balance = token.balanceOf(admin)
    assert token.balanceOf(admin) > 0
    token.transfer(injector, token.balanceOf(admin), {"from": admin})
    assert token.balanceOf(admin) == 0
    injector.sweep(token, {"from": admin})
    assert token.balanceOf(admin) >= admin_balance
    assert token.balanceOf(admin) + token.balanceOf(injector) == system_balance
    with brownie.reverts("Only callable by owner"):
        injector.sweep(token, {"from": deployer})

def test_sweep_multitoken(admin, injector, token, deployer, token_list):
    for test_token in token_list:
        tok = Contract(test_token)
        system_balance = tok.balanceOf(admin) + tok.balanceOf(injector)
        admin_balance = tok.balanceOf(admin)
        assert tok.balanceOf(admin) > 0
        tok.transfer(injector, tok.balanceOf(admin), {"from": admin})
        assert tok.balanceOf(admin) == 0
        injector.sweep(tok, {"from": admin})
        assert tok.balanceOf(admin) >= admin_balance
        assert tok.balanceOf(admin) + tok.balanceOf(injector) == system_balance
        with brownie.reverts("Only callable by owner"):
            injector.sweep(token, {"from": deployer})

def test_setDistributorToOwner(admin, injector, gauge, token, deployer, token_list):
    assert(gauge.reward_data(token.address)[0] == injector.address)
    injector.setDistributorToOwner(gauge.address,token.address,{'from':injector.owner()})
    assert(gauge.reward_data(token.address)[0] == injector.owner() )

def test_manualDeposit(admin, injector, gauge, token, deployer, token_list):
    amount = 100*10**18
    gauge.set_reward_distributor(token.address,injector.address,{'from':injector.owner()})
    token.transfer(injector.address, 1000 * 10 ** 18, {'from': admin})
    injector.manualDeposit(gauge.address,token.address,amount,{'from':injector.owner()})
    assert(gauge.reward_data(token.address)[3] == chain.time() )

def test_validatedSuccess(admin, injector, gauge, token, gauge2):

    # throw all current tokens away
    token.transfer(token.address,token.balanceOf(injector.address),{'from':injector.address})
    assert(token.balanceOf(injector) == 0)
    token.transfer(injector.address, 950 * 10 ** 18, {'from': admin})

    injector.setRecipientList([], [], [], {'from': admin})
    injector.setValidatedRecipientList([gauge,gauge2],[50*10**18,150*10**18],[4,5],{'from':admin})
    assert injector.checkExactBalancesMatch({'from':admin})
    injector.injectFunds([gauge,gauge2],{'from':admin})
    # sleep 8 days
    chain.sleep(60*60*24*8)
    chain.mine()
    injector.injectFunds([gauge, gauge2],{'from':admin})
    assert injector.checkExactBalancesMatch({'from':admin})

# tests to make sure checkUpkeepBalance (which gets called on setValidatedRecipient)
# returns false when sum of scheduled distributions don't add up to current balance
def test_validatedFail(admin, injector, gauge, token, gauge2):
    # throw all current tokens away
    token.transfer(token.address,token.balanceOf(injector.address),{'from':injector.address})
    assert(token.balanceOf(injector) == 0)
    # Note: amount is changed to 1000, but total sum needed is 950
    token.transfer(injector.address, 1000 * 10 ** 18, {'from': admin})

    injector.setRecipientList([], [], [], {'from': admin})

    with brownie.reverts("balance doesn't match for supplied schedules"):
        injector.setValidatedRecipientList([gauge, gauge2], [50 * 10 ** 18, 150 * 10 ** 18], [4, 5], {'from': admin})

    injector.setRecipientList([gauge, gauge2], [50 * 10 ** 18, 150 * 10 ** 18], [4, 5], {'from': admin})
    assert(injector.checkExactBalancesMatch({'from':admin}) == False)


# add 4 gauges, ru na program, remove them, add osme that are the same,
def test_addAndRemoveStuff(admin, injector, gauge, token, gauge2,upkeep_caller):
    # throw all current tokens away
    token.transfer(token.address,token.balanceOf(injector.address),{'from':injector.address})
    assert(token.balanceOf(injector) == 0)
    start_balance = 1100
    token.transfer(injector.address, start_balance * 1e18, {'from': admin})


    injector.setRecipientList([], [], [], {'from': admin})
    chain.sleep(60*60*24*8)
    chain.mine()
    amt1 = 100 * 1e18
    amt2 = 25 * 1e18
    injector.setRecipientList([gauge,gauge2], [amt1,amt2], [3,4], {'from':admin})
    (upkeepNeeded, performData) = injector.checkUpkeep("", {"from": upkeep_caller})
    injector.performUpkeep(performData, {'from':upkeep_caller})

    new_balance = token.balanceOf(injector)
    assert((start_balance * 1e18 ) - new_balance == amt1 + amt2)
    chain.sleep(60*60*24*8)
    chain.mine()
    injector.setRecipientList([gauge2], [amt2], [4], {'from': admin})
    (upkeepNeeded, performData) = injector.checkUpkeep("", {"from": upkeep_caller})
    injector.performUpkeep(performData, {'from':upkeep_caller})
    newer_balance = token.balanceOf(injector)
    assert(new_balance - newer_balance == amt2 )
