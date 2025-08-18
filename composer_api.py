from __future__ import annotations

from typing import Dict, Any, Optional
from logger_config import setup_logger
from dotenv import load_dotenv
import httpx
import os

load_dotenv()
logger = setup_logger('composer_api', 'logs/composer.log')

# --- Config (override via .env as needed) ---
COMPOSER_API_BASE    = "https://stagehand-api.composer.trade/api/v1"
COMPOSER_API_KEY     = os.getenv("COMPOSER_API_KEY", "").strip()
COMPOSER_API_SECRET  = os.getenv("COMPOSER_API_SECRET", "").strip()  # the token string after "Bearer "
COMPOSER_ACCOUNT_NUM = os.getenv("COMPOSER_ACCOUNT_NUM", "").strip()

# Endpoints
ACCOUNTS_PATH              = "/accounts/list"                       
ACCOUNT_HOLDINGS_PATH_TMPL = "/portfolio/accounts/{account_uuid}/holding-stats" 
SYMPHONY_PATH_TMPL         = "/symphonies/{symphony_id}"       

def _get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """HTTP GET helper with Composer auth."""
    url = f"{COMPOSER_API_BASE}{path}"
    headers = {
            "x-origin": 'public-api',
            "x-api-key-id": COMPOSER_API_KEY,
            "Authorization": f"Bearer {COMPOSER_API_SECRET}",
            "accept": "application/json",
        }
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(f"Composer GET {path} failed: {resp.status_code} {resp.text}")
        return resp.json()

def list_accounts() -> Any:
    """List Composer brokerage accounts for the API user."""
    return _get(ACCOUNTS_PATH)

def _normalize_positions_to_percentages(positions: Any):
    """Accept flexible shapes and derive % by market value.
    """
    # Try market value first
    percentages = {"assets": {}, "percentages": {}, "portfolio_total": 0.0}
    check_sum = 0.0
    for row in positions:
        asset = row.get("asset_class")
        sym = row.get("symbol")
        symph = row.get("symphony")
        
        if not sym or asset is None or asset.lower() != "equities" or not symph:
            if sym != "$USD":
                continue
        # If its in a symphony grab its percentage and assets
        alloc = symph.get("allocation")
        if alloc is not None:
            percentages["percentages"][sym] = round(row["symphony"]["allocation"]*100, 2) 
            percentages["assets"][sym] = {
                'current_price': row.get('price'),
                'market_value': symph.get("value"),
                'qty': symph.get("amount"),
                'rounded_qty': round(symph.get("amount"), 2)
            }
            percentages["portfolio_total"] += symph.get("value")
            check_sum += percentages["percentages"][sym]
    
    percentages["percentages"]["checksum"] = check_sum
    return percentages

def get_account_data(account_uuid: str):
    """Pull holdings for a Composer brokerage account and convert to % of portfolio.

    Args:
        account_id: The Composer brokerage account id.
    """
    path = ACCOUNT_HOLDINGS_PATH_TMPL.format(account_uuid=account_uuid)
    data = _get(path)
    # Try common keys: positions, holdings, assets
    positions = data.get("holdings")
    if not isinstance(positions, list):
        raise RuntimeError(f"Unexpected payload for account holdings: {type(positions)}")
    return _normalize_positions_to_percentages(positions)

def get_symphony_percentages(symphony_id: str):
    """Pull a single symphony definition and convert its weights to percentages.

    Args:
        symphony_id: The Composer symphony id.
    """
    return None

def get_composer_percentages() -> Dict[str, Any]:
    accounts = list_accounts()
    logger.info(f"Composer accounts: {accounts}")
    if accounts:
        account_uuid = None
        
        # Find the account UUID for the specified account number
        for account in accounts["accounts"]:
            if account.get("account_number") == COMPOSER_ACCOUNT_NUM:
                account_uuid = account["account_uuid"]
                break
        
        if not account_uuid:
            raise RuntimeError(f"Account number {COMPOSER_ACCOUNT_NUM} not found in Composer accounts.")
        
        percentages = get_account_data(account_uuid)
        logger.info(f"Account {account_uuid} percentages: {percentages}")
    
        return percentages
    return None

if __name__ == "__main__":
    pass