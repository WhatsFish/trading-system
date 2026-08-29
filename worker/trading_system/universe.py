from dataclasses import dataclass


@dataclass(frozen=True)
class Asset:
    instrument: str
    name: str
    group: str


ASSETS = (
    Asset("SPY-USDT-SWAP", "S&P 500 ETF", "index"),
    Asset("QQQ-USDT-SWAP", "Nasdaq-100 ETF", "index"),
    Asset("AAPL-USDT-SWAP", "Apple", "technology"),
    Asset("AMZN-USDT-SWAP", "Amazon", "technology"),
    Asset("AMD-USDT-SWAP", "AMD", "technology"),
    Asset("AVGO-USDT-SWAP", "Broadcom", "technology"),
    Asset("GOOGL-USDT-SWAP", "Alphabet", "technology"),
    Asset("META-USDT-SWAP", "Meta", "technology"),
    Asset("MSFT-USDT-SWAP", "Microsoft", "technology"),
    Asset("NVDA-USDT-SWAP", "NVIDIA", "technology"),
    Asset("JNJ-USDT-SWAP", "Johnson & Johnson", "healthcare"),
    Asset("LLY-USDT-SWAP", "Eli Lilly", "healthcare"),
    Asset("MRK-USDT-SWAP", "Merck", "healthcare"),
    Asset("UNH-USDT-SWAP", "UnitedHealth", "healthcare"),
)

BY_INSTRUMENT = {asset.instrument: asset for asset in ASSETS}
DEFAULT_INSTRUMENTS = tuple(asset.instrument for asset in ASSETS)

