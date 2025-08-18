from alpaca.trading.client import TradingClient
from logger_config import setup_logger
from dotenv import load_dotenv
import yaml
import os

# Load environment variables from .env file
load_dotenv()

PAPER = os.getenv("PAPER")
PAPER = True if PAPER.lower() == "true" else False

logger = setup_logger('alpaca_api', 'logs/alpaca.log')

def get_alpaca_percentages():
    """Used to collect the position percentages

    Args:
        paper (bool, optional): Dictate if paper account or not. Defaults to False.

    Returns:
        dict: Dict of assets and their percent of the portfolio
    """
    trading_client = TradingClient(os.getenv('ALPACA_API_KEY'), os.getenv('ALPACA_SECRET_KEY'), paper=PAPER)
    holdings = trading_client.get_all_positions()
    # Collect the Assets
    assets = {}
    for asset in holdings:
        rounded_qty = round(float(asset.qty), 4)
        assets.update({asset.symbol: {"rounded_qty": rounded_qty,
                                      "qty": float(asset.qty),
                                      "current_price": float(asset.current_price),
                                      "market_value": round(float(asset.current_price) * rounded_qty, 2)}})
    
    portfolio_total = round(sum([asset["market_value"] for asset in assets.values()]), 6)
    # Convert to percentages
    percentages = {}
    per_checksum = 0
    for asset, qty in assets.items():
        amount = round((qty["market_value"]/portfolio_total)*100, 2)
        per_checksum += amount
        percentages.update({asset: amount})

    # Lets validate that we have the correct percentage
    if per_checksum < 99:
        raise Exception("Invalid Checksum")
    
    percentages.update({"checksum": per_checksum})

    return {"percentages": percentages,
            "assets": assets,
            "portfolio_total": portfolio_total} 

    
if __name__ == '__main__':
    pass