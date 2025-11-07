import requests
import time
import os
import random
import concurrent.futures
import threading
from typing import Dict, Optional, List, Tuple
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

#usdt contract
USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

def load_proxies(proxy_file: str) -> List[Dict]:
    """Load proxies from file"""
    proxies = []
    try:
        with open(proxy_file, "r") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                    
                proxy_parts = line.split(":")
                if len(proxy_parts) == 4:
                    ip, port, username, password = proxy_parts
                    proxy_url = f"http://{username}:{password}@{ip}:{port}"
                    proxies.append({"http": proxy_url, "https": proxy_url})
                elif len(proxy_parts) == 2:
                    ip, port = proxy_parts
                    proxy_url = f"http://{ip}:{port}"
                    proxies.append({"http": proxy_url, "https": proxy_url})
        print(f"✅ Loaded {len(proxies)} proxies from {proxy_file}")
        return proxies
    except FileNotFoundError:
        print(f"⚠️  Proxy file '{proxy_file}' not found. Running without proxies.")
        return []
    except Exception as e:
        print(f"❌ Error loading proxies: {e}")
        return []

def create_retry_session():
    session = requests.Session()
    retries = Retry(
        total=3,  
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504, 429],
    )
    session.mount('https://', HTTPAdapter(max_retries=retries))
    session.timeout = 15
    return session

def get_balances(wallet_address: str, session: requests.Session, proxy: Optional[Dict] = None) -> Tuple[float, float]:
    """Get TRX and USDT balances for a wallet address"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json"
        }
        tron_api_key = os.getenv("TRON_PRO_API_KEY")
        if tron_api_key:
            headers["TRON-PRO-API-KEY"] = tron_api_key
        
        response = session.get(
            f"https://api.trongrid.io/v1/accounts/{wallet_address}",
            proxies=proxy,
            headers=headers,
            timeout=15
        )
        data = response.json()
        
        if not data.get("data") or len(data["data"]) == 0:
            return 0.0, 0.0
            
        account_obj = data["data"][0]
        trx_balance = int(account_obj.get("balance", 0)) / 1_000_000
        
        usdt_balance = 0.0
        try:
            trc20_inline = account_obj.get("trc20", [])
            if isinstance(trc20_inline, list):
                for entry in trc20_inline:
                    if isinstance(entry, dict) and USDT_CONTRACT in entry:
                        raw_val = entry.get(USDT_CONTRACT, "0")
                        usdt_balance = int(str(raw_val)) / 1_000_000
                        break
        except Exception:
            pass

        if usdt_balance == 0.0:
            trc20_url = f"https://api.trongrid.io/v1/accounts/{wallet_address}/trc20"
            response = session.get(trc20_url, proxies=proxy, headers=headers, timeout=15)
            data = response.json()

        def parse_token_balance(balance_value, decimals_hint=None):
            try:
                if isinstance(balance_value, (int, float)):
                    raw = float(balance_value)
                    if decimals_hint is None:
                        decimals_hint = 6
                    return raw / (10 ** int(decimals_hint))
                if isinstance(balance_value, str):
                    if "." in balance_value:
                        return float(balance_value)
                    raw_int = int(balance_value)
                    if decimals_hint is None:
                        decimals_hint = 6
                    return raw_int / (10 ** int(decimals_hint))
            except Exception:
                return 0.0
            return 0.0

        if usdt_balance == 0.0 and data is not None:
            trc20_data = data.get("data", []) if isinstance(data, dict) else data
            for token in trc20_data:
                if not isinstance(token, dict):
                    continue
                if token.get("contract_address") == USDT_CONTRACT:
                    usdt_balance = parse_token_balance(token.get("balance", "0"), token.get("decimals", 6))
                    break
                token_info = token.get("token_info") or token.get("tokenInfo")
                if isinstance(token_info, dict) and token_info.get("address") == USDT_CONTRACT:
                    usdt_balance = parse_token_balance(token.get("balance", "0"), token.get("tokenDecimal") or token_info.get("decimals") or 6)
                    break
                if USDT_CONTRACT in token:
                    usdt_balance = parse_token_balance(token.get(USDT_CONTRACT, "0"), 6)
                    break
                symbol = token.get("symbol") or token.get("tokenAbbr") or token.get("tokenAbbreviation")
                name = token.get("name")
                contract_addr = token.get("tokenId") or token.get("contractAddress")
                if (symbol == "USDT" or name == "Tether USD" or contract_addr == USDT_CONTRACT):
                    usdt_balance = parse_token_balance(token.get("balance") or token.get("quantity") or token.get("amount") or "0", token.get("decimals") or token.get("tokenDecimal") or 6)
                    break

        if usdt_balance == 0.0:
            try:
                tronscan_url = f"https://apilist.tronscanapi.com/api/account/tokens?address={wallet_address}&token=trc20"
                rs = session.get(tronscan_url, proxies=proxy, headers=headers, timeout=15)
                js = rs.json()
                token_list = []
                if isinstance(js, dict):
                    token_list = (js.get("data") or []) + (js.get("tokens") or [])
                elif isinstance(js, list):
                    token_list = js
                for t in token_list:
                    if not isinstance(t, dict):
                        continue
                    t_symbol = t.get("tokenAbbreviation") or t.get("tokenAbbr") or t.get("symbol")
                    t_contract = t.get("contractAddress") or t.get("tokenId")
                    if t_symbol == "USDT" or t_contract == USDT_CONTRACT or t.get("name") == "Tether USD":
                        decimals = t.get("tokenDecimal") or t.get("decimals") or 6
                        bal_field = t.get("balance") or t.get("quantity") or t.get("amount") or "0"
                        usdt_balance = parse_token_balance(bal_field, decimals)
                        break
            except Exception:
                pass

        return trx_balance, usdt_balance
        
    except Exception as e:
        raise e

def process_address(address: str, proxies: List[Dict], retry_count: int = 3) -> Tuple[str, Optional[float], Optional[float]]:
    """Process a single address with retry logic"""
    address = address.strip()
    if not address:
        return address, None, None
        
    session = create_retry_session()
    
    for attempt in range(retry_count):
        proxy = random.choice(proxies) if proxies else None
        
        try:
            if attempt == 0 and proxy:
                print(f"🔍 Checking {address} (attempt {attempt + 1}) with proxy...")
            elif attempt == 0:
                print(f"🔍 Checking {address} (attempt {attempt + 1}) without proxy...")
            else:
                print(f"🔄 Retrying {address} (attempt {attempt + 1})...")
                
            trx_balance, usdt_balance = get_balances(address, session, proxy)
            
            if trx_balance > 0 or usdt_balance > 0:
                print(f"💰 {address} => TRX: {trx_balance}, USDT: {usdt_balance}")
            else:
                print(f"💸 {address} => TRX: 0, USDT: 0")
                
            return address, trx_balance, usdt_balance
            
        except Exception as e:
            print(f"⚠️  Error for {address} (attempt {attempt + 1}): {str(e)}")
            if proxy and attempt == 0:
                proxies_copy = []
            time.sleep(1)  
    
    print(f"❌ Failed to get balance for {address} after {retry_count} attempts")
    return address, 0.0, 0.0

def load_addresses(file_path: str) -> List[str]:
    """Load addresses from file"""
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            addresses = [line.strip() for line in file if line.strip()]
        print(f"📋 Loaded {len(addresses)} addresses from {file_path}")
        return addresses
    except FileNotFoundError:
        print(f"❌ Address file '{file_path}' not found.")
        return []
    except Exception as e:
        print(f"❌ Error loading addresses: {e}")
        return []

def save_results(results: Dict[str, Tuple[Optional[float], Optional[float]]], output_file: str):
    """Save results to file"""
    try:
        with open(output_file, "w", encoding="utf-8") as file:
            total_trx = 0.0
            total_usdt = 0.0
            processed_count = 0
            
            for address, (trx_balance, usdt_balance) in results.items():
                if trx_balance is not None and usdt_balance is not None:
                    result = f"{address} trx_balance {trx_balance} Usdt_balance {usdt_balance}\n"
                    file.write(result)
                    total_trx += trx_balance
                    total_usdt += usdt_balance
                    processed_count += 1
                else:
                    file.write(f"{address} trx_balance 0 Usdt_balance 0\n")
                    processed_count += 1
            
            file.write("\n" + "-" * 50 + "\n")
            file.write(f"Total TRX Balance: {total_trx}\n")
            file.write(f"Total USDT Balance: {total_usdt}\n")
            file.write(f"Total Addresses Processed: {processed_count}\n")
            file.write("-" * 50 + "\n")
        
        print(f"\n✅ Results saved to: {output_file}")
        print(f"📊 Processed {processed_count} addresses")
        print(f"💰 Total TRX: {total_trx}")
        print(f"💰 Total USDT: {total_usdt}")
        
    except Exception as e:
        print(f"❌ Failed to save results: {e}")

def main():
    """Main function"""
    print("🚀 TRX & USDT Balance Checker (Multi-threaded)")
    print("=" * 50)
    
    ADDRESS_FILE = "trx_address.txt"
    OUTPUT_FILE = "trx_balance.txt"
    PROXY_FILE = "proxy.txt"
    MAX_WORKERS = 100
    RETRY_COUNT = 3
    
    proxies = load_proxies(PROXY_FILE)
    
    addresses = load_addresses(ADDRESS_FILE)
    if not addresses:
        print("❌ No addresses to check. Exiting.")
        return
    
    print(f"🔧 Using {MAX_WORKERS} threads with {len(proxies)} proxies")
    print("=" * 50)
    
    results = {}
    start_time = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_address = {
            executor.submit(process_address, address, proxies, RETRY_COUNT): address 
            for address in addresses
        }
        
        for future in concurrent.futures.as_completed(future_to_address):
            address, trx_balance, usdt_balance = future.result()
            results[address] = (trx_balance, usdt_balance)
    
    end_time = time.time()
    processing_time = end_time - start_time
    
    print("\n" + "=" * 50)
    print(f"⏱️  Processing completed in {processing_time:.2f} seconds")
    
    save_results(results, OUTPUT_FILE)
    
    non_zero_trx = sum(1 for trx, usdt in results.values() if trx and trx > 0)
    non_zero_usdt = sum(1 for trx, usdt in results.values() if usdt and usdt > 0)
    
    if non_zero_trx > 0 or non_zero_usdt > 0:
        print(f"🎉 Found {non_zero_trx} addresses with TRX and {non_zero_usdt} addresses with USDT!")
    else:
        print("😔 No TRX or USDT found in any addresses")

if __name__ == "__main__":
    main()
