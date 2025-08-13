from holdings_source import check_for_change, get_percentages, save_changes
from logger_config import setup_logger
from schwab_api import schwab_client
from dotenv import load_dotenv
import time
import os

__version__ = "2025.8.13"

logger = setup_logger('copy_trade', 'logs/copy_trade.log')

# Load environment variables from .env file
load_dotenv()

# --------------------------------------
# How often we want to check for changes
PERIOD = int(os.getenv('PERIOD'))
# How many times we want to retry actions
RETRY = int(os.getenv('RETRY'))
# How long we want to wait after changes are detected
CHANGE_WAIT = int(os.getenv('CHANGE_WAIT'))
# --------------------------------------

# How we run the copy trade method
if __name__ == '__main__':
    print(f"Version: {__version__}")
    print(f"Mode: {os.getenv("MODE").lower()}")
    schwab_conn = schwab_client()
    failed_account = set()
    while True:
        if len(failed_account) > 0:
            logger.error("\n!!! Some accounts have failed !!!\n")
            print("Some accounts have failed")
            # TODO: Lets send an Email/SMS that some accounts have failed
        
        if schwab_conn.is_token_valid() is False:
            # If the token is invalid lets get into an infinite loop of notifications
            logger.error("\n!!! Invalid Token !!!\n")
            print("Invalid Token")
            while True:
                pass
                # TODO: Lets send an Email/SMS that the token is Invalid 
                            
        # We are just going to check for changes and then copy trade instead of
        if check_for_change():
            logger.info("\n=== Change Detected ===\n")
            logger.info(f"Waiting for {CHANGE_WAIT} seconds before executing trades")
            print(f"Waiting for {CHANGE_WAIT} seconds before executing trades")
            time.sleep(CHANGE_WAIT)
            # Grab the percentages once to use for the day
            perctanges = get_percentages()
            for account_num in os.getenv('SCHWAB_ACCOUNT_NUMS').replace(" ", "").split(","):
                if account_num in failed_account:
                    logger.error(f"Account Num: {account_num} is in being skipped due to failure")
                    continue
                try:
                    print(f"Buying Tickers in Account Num: {account_num}")
                    schwab_conn.buy_tickers_for_the_day(account_num, schwab_conn.breakdown_account_by_quotes(account_num, perctanges["percentages"]))
                except Exception as e:
                    logger.error(f"Account Num: {account_num} Error: {e}")
                    print(f"Account Num: {account_num} Error: {e}")
                    if "Account has to low of a balance" in str(e):
                        failed_account.add(account_num)
                        continue
                    
                    # Lets retry the action RETRY times
                    for i in range(RETRY):
                        try:
                            schwab_conn.buy_tickers_for_the_day(account_num, schwab_conn.breakdown_account_by_quotes(account_num, perctanges["percentages"]))
                            break
                        except Exception as e:
                            logger.error(f"Account Num: {account_num} Error: {e}")
                            print(f"Account Num: {account_num} Error: {e}")
                            time.sleep(PERIOD)
                        
                        failed_account.add(account_num)
            
            # Record the changes locally for tomorrow
            save_changes(perctanges)
        print("Awaiting Changes")
        time.sleep(PERIOD)
            