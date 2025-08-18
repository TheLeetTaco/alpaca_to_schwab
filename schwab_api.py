from schwab.orders.equities import equity_buy_market, equity_sell_market
from logger_config import setup_logger
from schwab.auth import easy_client, client_from_manual_flow, client_from_token_file
from dotenv import load_dotenv
from schwab.utils import Utils
from pprint import pformat
from enum import Enum
import httpx
import math
import time
import os

# Load environment variables from .env file
load_dotenv()

logger = setup_logger('schwab_api', 'logs/schwab.log')

class Modes(Enum):
    # Run logic but only log orders
    DEBUG = 1,
    # Run logic and send orders to broker
    LIVE = 2,
    
class ShareRounding(Enum):
    # Your typical roudning .5+ goes to 1 .5- goes to 0
    NEAREST = 1,
    # Rounds down .99 goes to 0
    DOWN = 2,

# --------------------------------------
# Used to dictate if orders are real or not
match os.getenv("MODE").lower():
    case "live":
        MODE = Modes.LIVE
    case _:
        MODE = Modes.DEBUG
# Percentage of account equity to trade with (i.e. 1%-100%)
TRADE_WITH = float(os.getenv("TRADE_WITH"))
# In the above example, using 90% with a 500$ padding:
#  Account equity = $100,000 * .90 = $90,000 - $500 = $89,500.  
#  This is the amount that will be used as the starting point for all calculations when determining how many shares to purchase, etc.  
#  This allows for some slippage, etc.
# Minimum value for padding is $500
PADDING = float(os.getenv("PADDING"))
# Which way to round shares
match os.getenv("SHARE_ROUND").lower():
    case "near":
        SHARE_ROUND = ShareRounding.NEAREST
    case "down":
        SHARE_ROUND = ShareRounding.DOWN
    case _:
        raise Exception("Invalid Share Round")
# Sell timeout
SELL_TIMEOUT = int(os.getenv("SELL_TIMEOUT"))
# Order timeout
ORDER_WAIT = int(os.getenv("ORDER_WAIT"))
# --------------------------------------

def create_client():
    """Simple function to create a client to use

    Returns:
        Schwab Client
    """
    if os.getenv("HOSTING_ENV").lower().strip() == "cloud":
        if os.path.exists(os.getenv("TMP_TOKEN_PATH")):
            # If we have a token lets use it
            return client_from_token_file(token_path=os.getenv("TMP_TOKEN_PATH"), 
                                        api_key=os.getenv("SCWAHB_API_KEY"),
                                        app_secret=os.getenv("SCWAHB_SECRET_KEY"))
        else:
            return client_from_manual_flow(api_key=os.getenv("SCWAHB_API_KEY"), app_secret=os.getenv("SCWAHB_SECRET_KEY"),callback_url=os.getenv("CALLBACK_URL"), token_path=os.getenv("TMP_TOKEN_PATH"))
    else:
        return easy_client(api_key=os.getenv("SCWAHB_API_KEY"), app_secret=os.getenv("SCWAHB_SECRET_KEY"),callback_url=os.getenv("CALLBACK_URL"), token_path=os.getenv("TMP_TOKEN_PATH"))
    
def read_in_accounts() -> set:
    """Grabs the accounts from the env

    Returns:
        set: of Accounts
    """
    # Lets grab the accounts
    accounts = os.getenv("SCHWAB_ACCOUNT_NUMS").strip()
    # Trim accidental end commans
    if accounts[-1] == ",":
        accounts = accounts [:-1]
    # Split out into a set
    if "," in accounts:
        accounts = set(accounts.split(","))
    else:
        accounts = set(accounts)
        
    return accounts

class schwab_client:
    def __init__(self) -> None:
        self.c = create_client()

    def is_token_valid(self) -> bool:
        """Used to check if token is valid

        Returns:
            bool: True/False on if token is still valid
        """
        resp = self.c.get_account_numbers()
        
        if resp.status_code == httpx.codes.OK:
            logger.info("-- Token was found to be active ---")
            return True
        
        logger.info("!!! Token was found to be not active !!!")
        return False

    def access_to_expected_accounts(self) -> bool:
        """Used to check if expected accounts are returned

        Returns:
            bool: True/False on if expected accounts were found
        """
        
        resp = self.c.get_account_numbers()
        
        if resp.status_code != httpx.codes.OK:
            logger.error("!!! Failed to grab accounts !!!")
            return False

        # Lets grab the accounts we are expecting
        expected_accounts = read_in_accounts()
        
        ret_accounts = set()
        for account in resp.json():
            ret_accounts.add(account["accountNumber"])

        return ret_accounts == expected_accounts
            
    def get_quotes(self, symbols: set):
        """Used to collected

        Args:
            symbols (set): Set of Symbols to get quotes for
        """
        resp = self.c.get_quotes(symbols=symbols)
        
        if resp.status_code != httpx.codes.OK:
            logger.error("!!! Failed to grab Quote information !!!")
            return False
        
        return resp.json()

    def get_account_hash(self, account_num: int):
        """Used to get an accounts hash data

        Args:
            account_num (int): account num to get hash for

        Returns:
            str/None: str when found and None when not 
        """
        resp = self.c.get_account_numbers()
        
        if resp.status_code != httpx.codes.OK:
            logger.error("!!! Failed to get accounts !!!")
            raise Exception("!!! Failed to get accounts !!!")
        
        account_hashes = resp.json()
        # Convert the List of dictionaries into a dict
        account_hashes = {account.get("accountNumber"): account.get("hashValue") for account in account_hashes}
        return account_hashes.get(account_num, None)
    
    def get_accout_details(self, account_num: int):
        """Used to get account details

        Args:
            account_num (int): account number

        Returns:
            dict/None: dictionary of account details or None
        """
        account_hash = self.get_account_hash(account_num)

        if account_hash is None:
            logger.error("!!! Failed to get account hash !!!")
            raise Exception("!!! Failed to get account hash !!!")
        
        resp = self.c.get_account(account_hash, fields=[self.c.Account.Fields.POSITIONS])

        if resp.status_code != httpx.codes.OK:
            logger.error("!!! Failed to get account !!!")
            raise Exception("!!! Failed to get account !!!")

        account_details = resp.json()
        
        return account_details
    
    def get_account_holdings(self, account_num: int):
        """Used to get the holdings of an account

        Args:
            account_num (int): account number

        Returns:
            dict/None: dictionary of holdings or None
        """
        details = self.get_accout_details(account_num)
        
        if details is None:
            raise Exception("!!! Failed to get account details !!!")
        
        return details["securitiesAccount"]["positions"]
    
    def get_account_holding_value(self, account_num: int):
        """Used to collect the value of the 

        Args:
            account_num (str): hash of account to interact with
        """
        details = self.get_accout_details(account_num)
        
        if details is None:
            raise Exception("!!! Failed to get account details !!!")
        
        return details["securitiesAccount"]["currentBalances"]["liquidationValue"]
    
    def get_current_holdings(self, account_num: int):
        """Used to get the current holdings of an account

        Args:
            account_num (int): account number

        Returns:
            dict/None: dictionary of holdings or None
        """
        details = self.get_accout_details(account_num)
        
        if details is None:
            raise Exception("!!! Failed to get account details !!!")
        
        stocks = {}
        
        if details["securitiesAccount"].get("positions") is None:
            return {}
        
        for stock in details["securitiesAccount"]["positions"]:
            stocks[stock["instrument"]["symbol"]] = int(stock["longQuantity"])
        
        return stocks
    
    def get_account_trade_value(self, account_num: int):
        """Used to find how much of the account to trade with

        Args:
            account_num (int): account number

        Returns:
            int/None: int value or None if not found
        """
        account_total = self.get_account_holding_value(account_num)

        if account_total is None:
            logger.error("!!! Failed to get account hash !!!")
            raise Exception("!!! Failed to get account hash !!!")
        
        if account_total < 1.0:
            logger.error("!!! Account has to low of a balance !!!")
            raise Exception("!!! Account has to low of a balance !!!")
        
        logger.info(f"\nAccount Total: {account_total} Trading with: {TRADE_WITH}% Padding: {PADDING}\nCalculated Trade Value: {round(account_total * (TRADE_WITH/100) - PADDING, 2)}\nCalculation: (Account Total * (Trading With/100) - Padding) Rounded to two decimals")
        return round(account_total * (TRADE_WITH/100) - PADDING, 2)

    def breakdown_account_by_quotes(self, account_num: int, percentages: dict) -> dict:
        """Used to breakout an accounts value by the percentages from Alpaca, TRADE_WITH, and PADDING

        Args:
            account_num (str): num of account to interact with
            percentages (dict): Percentage breakdown from Alpaca

        Returns:
            dict: Breakdown of the amount of each ticker to buy
        """
        logger.info(f"\n=== \nPercentages being used for breakdown \n{pformat(percentages)}\n===")
        
        total = self.get_account_trade_value(account_num)
        
        if percentages.get("$USD") is not None:
            logger.info("!!! Found $USD in assets, Extra Padding will be used !!!")
            extra_padding = percentages.pop("$USD", None)
            remove = total * (extra_padding / 100)
            total -= remove
            logger.info(f"!!! Removing ${remove} from total for Cash held by Symphonies !!!")
            
            
        check_sum = 0
        for stock in percentages:
            percentages[stock] = round(total * percentages[stock]/100, 2)
            if stock != "checksum":
                check_sum += percentages[stock]
        
        logger.info(f"\n=== \n(What will be applied to Schwab account)\nBreaking down account {account_num} using account value of ${total}\nChecksum: {round(check_sum, 2)}\nBreakdown:\n{pformat(percentages)}\n===")
        
        ticker_quotes = {key for key in percentages.keys()}
        ticker_quotes.remove("checksum")
        ticker_data = self.get_quotes(ticker_quotes)
        
        buy_amounts = {}
        quotes = {}
        for stock in percentages:
            # We want to ignore the checksum
            if stock == "checksum":
                continue
            # Compile the quotes into a single dictionary for logging
            quotes[stock] = ticker_data[stock]["quote"]["mark"]
            # Based on setting we may want to round differently
            if SHARE_ROUND is ShareRounding.NEAREST:
                buy_amounts[stock] = round(percentages[stock]/quotes[stock] )
            elif SHARE_ROUND is ShareRounding.DOWN:
                buy_amounts[stock] = math.floor(percentages[stock]/quotes[stock] )
        
        rounding = "Nearest" if SHARE_ROUND is ShareRounding.NEAREST else "Down"
        
        logger.info(f"\n=== Quotes used: \n{pformat(quotes)} \n===")
        logger.info(f"\n=== Ticker buy amounts based on above Totals/Quotes w/ {rounding} Rounding \n{pformat(buy_amounts)}\n===")
        
        return buy_amounts

    def check_orders_for_completion(self, account_num: str, orders: list):
        """Used to check for orders

        Args:
            account_hash (str): hash of account to interact with
        """
        account_hash = self.get_account_hash(account_num)
        
        if account_hash is None:
            return False
        
        order_details = []
        for order in orders:
            order_details.append(self.c.get_order(order, account_hash).json())
        
        for order in order_details:
            if order["status"] != "FILLED":
                return False
            
        return True

    def sell_tickers(self, account_num: int, tickers: dict):
        """Used to sell tickers

        Args:
            account_num (int): account number
            tickers (dict): dictionary of tickers to sell
        """
        account_hash = self.get_account_hash(account_num)
        
        if account_hash is None:
            return False
        
        orders = []
        for ticker, quantity in tickers.items():
            if quantity == 0:
                logger.info(f"!!! Skipping {ticker} as quantity is 0 !!!")
                continue
            logger.info(f"!!! Selling {quantity} of {ticker} !!!")
            orders.append(Utils(self.c, account_hash).extract_order_id(self.c.place_order(account_hash, equity_sell_market(symbol=ticker, quantity=quantity).build())))
        
        return orders

    def buy_tickers(self, account_num: int, tickers: dict):
        """Used to buy tickers

        Args:
            account_num (int): account number
            tickers (dict): dictionary of tickers to buy
        """
        account_hash = self.get_account_hash(account_num)
        
        if account_hash is None:
            return False
        
        orders = []
        for ticker, quantity in tickers.items():
            if quantity == 0:
                logger.info(f"!!! Skipping {ticker} as quantity is 0 !!!")
                continue
            logger.info(f"!!! Buying {quantity} of {ticker} !!!")
            orders.append(Utils(self.c, account_hash).extract_order_id(self.c.place_order(account_hash, equity_buy_market(symbol=ticker, quantity=quantity).build())))
        
        return

    def buy_tickers_for_the_day(self, account_num: int, tickers: dict):
        """Buy orders for the day based on alpaca changes

        Args:
            account_hash (str): hash of account to interact with
            tickers (dict): Dictionary of new tickers to buy
        """

        old = self.get_current_holdings(account_num)
        new = tickers
        logger.info(f"=== Old Holdings ===\n{pformat(old)}")
        logger.info(f"=== New Holdings ===\n {pformat(new)}")
        
        added_keys = {key: new[key] for key in new if key not in old}
        removed_keys = {key: old[key] for key in old if key not in new}
        changed_keys = {key: {'old': old[key], 'new': new[key]} for key in old if key in new and old[key] != new[key]}
        
        differences = {
            "added": added_keys,
            "removed": removed_keys,
            "changed": changed_keys
        }
        logger.info(f"=== Differences between old and new holdings ===\n{pformat(differences)}")
        # Log the orders submitted for sells
        # Execute sell orders
        
        for key in changed_keys:
            new = changed_keys[key]["new"]
            old = changed_keys[key]["old"]
            logger.info("Adjusting added/removed keys")
            if new > old:
                logger.info(f"Adding {key} to added keys old holdings: {old} new holdings: {new}")
                if added_keys.get(key) is not None:
                    added_keys[key] += new - old
                else:
                    added_keys[key] = new - old
            elif new < old:
                logger.info(f"Adding {key} to removed keys old holdings: {old} new holdings: {new}")
                if removed_keys.get(key) is not None:
                    removed_keys[key] += old - new
                else:
                    removed_keys[key] = old - new
        
        adjusted_differences = {
            "added": added_keys,
            "removed": removed_keys
        }
        
        logger.info(f"=== (Adjusted) Differences between old and new holdings ===\n{pformat(adjusted_differences)}")
        
        if MODE is Modes.DEBUG:
            logger.info("!!! Debug Mode Skipping Buy/Sell Orders !!!")
        elif MODE is Modes.LIVE:
            count = SELL_TIMEOUT
            
            sell_orders = self.sell_tickers(account_num, removed_keys)
            if sell_orders is not None:
                logger.info(f"!!! Sell Order IDs: {pformat(sell_orders)} !!!")
                while self.check_orders_for_completion(account_num, sell_orders) is False:
                    if count == 0:
                        logger.error("!!! Aborting Sell Orders !!!")
                        print("!!! Aborting Sell Orders !!!")
                        for order in sell_orders:
                            self.c.cancel_order(order, self.get_account_hash(account_num))
                        raise Exception(f"!!! Failed to complete sell orders in under {SELL_TIMEOUT} seconds !!!")
                    count -= 1
                    logger.info("Checking for sell orders completion")
                    time.sleep(1)
            logger.info("--- Sell Orders Completed ---")
            
            logger.info(f"--- Going to sleep for {ORDER_WAIT} between orders ---")
            time.sleep(ORDER_WAIT)
            
            logger.info("--- Starting Buy Orders ---")
            buy_orders = self.buy_tickers(account_num, added_keys)
            if buy_orders is not None:
                logger.info(f"!!! Buy Order IDs: {pformat(buy_orders)} !!!")
                while self.check_orders_for_completion(account_num, buy_orders) is False:
                    logger.info("Checking for buy orders completion")
                    time.sleep(1)
        else:
            pass

if __name__ == '__main__':
    pass