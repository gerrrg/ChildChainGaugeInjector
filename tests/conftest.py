import pytest
import time
from brownie import (
    interface,
    accounts,
    ChildChainGaugeInjector,
    Contract,
    injectorFactory
)
from dotmap import DotMap
import pytest


##  Accounts
## addresses are for polygon
STREAMER_ADDRESS = "0x3Eae4a1c2E36870A006E816930d9f55DF0a72a13"
STREAMER_ADDRESS2 = "0xc7e5FE004416A96Cb2C7D6440c28aE92262f7695"
STREAMER_OWNER_ADDRESS = "0xAB093cd16e765b5B23D34030aaFaF026558e0A19" ## authorizer-adaptor
ARBI_WSTETH_USDC_WHALE = "0x3bAbEBfD684506A5B47701ee231A53427Ad413Ef"
ARBI_LDO_WHALE = "0x8565faab405b06936014c8b6bd5ab60376cc051b"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ARBI_LDO_ADDRESS = "0xC3C7d422809852031b44ab29EEC9F1EfF2A58756"
WEEKLY_INCENTIVE = 200*10**18
LM_MULTISIG ="0xc38c5f97B34E175FFd35407fc91a937300E33860"
## weth, usdt, usdc
TOKEN_LIST = [
    "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
    "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",
    "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"
]


@pytest.fixture(scope="module")
def get_rewards():
    return "0x1afe22a6"  # get_rewards has function selector "0x1afe22a6"

@pytest.fixture(scope="module")
def admin():
    return ARBI_LDO_WHALE



@pytest.fixture(scope="module")
def whale():
    return ARBI_WSTETH_USDC_WHALE


@pytest.fixture(scope="module")
def gauge():
    return Contract(STREAMER_ADDRESS)

@pytest.fixture(scope="module")
def gauge2():
    return Contract(STREAMER_ADDRESS2)

@pytest.fixture(scope="module")
def authorizer_adaptor():
    return STREAMER_OWNER_ADDRESS

@pytest.fixture(scope="module")
def authorizer_entrypoint():
    return Contract(STREAMER_OWNER_ADDRESS)

@pytest.fixture(scope="module")
def streamer():
    return Contract(STREAMER_ADDRESS)


@pytest.fixture(scope="module")
def upkeep_caller():
    return accounts[2]

@pytest.fixture()
def weekly_incentive():
    return WEEKLY_INCENTIVE
@pytest.fixture(scope="module")
def deployer():
    return accounts[0]


@pytest.fixture()
def injector(deploy):
    return deploy.injector


@pytest.fixture(scope="module")
def token():
    return interface.IERC20(ARBI_LDO_ADDRESS)

@pytest.fixture(scope="module")
def token_list():
    return TOKEN_LIST

@pytest.fixture(scope="module")
def factory(deployer, upkeep_caller, token):
    factory = injectorFactory.deploy(
        {'from':deployer}
    )
    return factory

@pytest.fixture(scope="module")
def deploy(deployer, admin, upkeep_caller, authorizer_adaptor, streamer, gauge, gauge2, get_rewards, token, authorizer_entrypoint,token_list, factory):
    """
    Deploys, vault and test strategy, mock token and wires them up.
    """

    # token.transfer(admin, 10000*10**18, {"from": ARBI_LDO_WHALE})

    tx = factory.createNewInjector(
        upkeep_caller,
        60*5, #minWaitPeriodSeconds
        token.address,
        admin,
        {"from": deployer}
    )
    injector = Contract.from_abi("injector",tx.return_value, ChildChainGaugeInjector.abi)
    print(token.balanceOf(deployer))
    # injector.transferOwnership(admin, {"from": deployer})

    injector.acceptOwnership({"from": admin})


    calldata = gauge.add_reward.encode_input(ARBI_LDO_ADDRESS,injector.address)
    try:
        authorizer_entrypoint.performAction(gauge.address,calldata,{'from':LM_MULTISIG})
        authorizer_entrypoint.performAction(gauge2.address, calldata, {'from': LM_MULTISIG})
    except:
        print("token already added")

    # calldata2 = gauge2.add_reward.encode_input(ARBI_LDO_ADDRESS,injector.address)
    # authorizer_entrypoint.performAction(gauge2.address, calldata, {'from': LM_MULTISIG})

    token.transfer(admin,1000*10**18,{'from':ARBI_LDO_WHALE})

    return DotMap(
        injector=injector,
        token=token,
        token_list=token_list
    )


