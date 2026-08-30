from dataclasses import dataclass


@dataclass(frozen=True)
class Asset:
    instrument: str
    name: str
    group: str


def asset(symbol: str, name: str, group: str) -> Asset:
    return Asset(f"{symbol}-USDT-SWAP", name, group)


ASSETS = (
    # Broad and sector benchmarks
    asset("SPY", "S&P 500 ETF", "index"),
    asset("QQQ", "Nasdaq-100 ETF", "index"),
    asset("SMH", "Semiconductor ETF", "index"),
    asset("XBI", "Biotech ETF", "index"),
    # Technology and internet
    asset("AAPL", "Apple", "technology"),
    asset("ADBE", "Adobe", "technology"),
    asset("AMZN", "Amazon", "technology"),
    asset("APP", "AppLovin", "technology"),
    asset("CRM", "Salesforce", "technology"),
    asset("CRWD", "CrowdStrike", "technology"),
    asset("CSCO", "Cisco", "technology"),
    asset("DELL", "Dell", "technology"),
    asset("GOOGL", "Alphabet", "technology"),
    asset("IBM", "IBM", "technology"),
    asset("META", "Meta", "technology"),
    asset("MSFT", "Microsoft", "technology"),
    asset("NET", "Cloudflare", "technology"),
    asset("NFLX", "Netflix", "technology"),
    asset("NOW", "ServiceNow", "technology"),
    asset("OKTA", "Okta", "technology"),
    asset("ORCL", "Oracle", "technology"),
    asset("PLTR", "Palantir", "technology"),
    asset("SHOP", "Shopify", "technology"),
    asset("SNOW", "Snowflake", "technology"),
    asset("TWLO", "Twilio", "technology"),
    asset("VRT", "Vertiv", "technology"),
    # Semiconductors and hardware
    asset("AMD", "AMD", "semiconductor"),
    asset("AMAT", "Applied Materials", "semiconductor"),
    asset("ARM", "Arm", "semiconductor"),
    asset("ASML", "ASML", "semiconductor"),
    asset("AVGO", "Broadcom", "semiconductor"),
    asset("CRDO", "Credo Technology", "semiconductor"),
    asset("INTC", "Intel", "semiconductor"),
    asset("KLAC", "KLA", "semiconductor"),
    asset("LRCX", "Lam Research", "semiconductor"),
    asset("MRVL", "Marvell", "semiconductor"),
    asset("MU", "Micron", "semiconductor"),
    asset("NVDA", "NVIDIA", "semiconductor"),
    asset("QCOM", "Qualcomm", "semiconductor"),
    asset("SMCI", "Super Micro Computer", "semiconductor"),
    asset("TSM", "TSMC", "semiconductor"),
    asset("WDC", "Western Digital", "semiconductor"),
    # Healthcare and biotechnology
    asset("HIMS", "Hims & Hers", "healthcare"),
    asset("ISRG", "Intuitive Surgical", "healthcare"),
    asset("JNJ", "Johnson & Johnson", "healthcare"),
    asset("LLY", "Eli Lilly", "healthcare"),
    asset("MRK", "Merck", "healthcare"),
    asset("MRNA", "Moderna", "healthcare"),
    asset("OSCR", "Oscar Health", "healthcare"),
    asset("UNH", "UnitedHealth", "healthcare"),
)

BY_INSTRUMENT = {item.instrument: item for item in ASSETS}
DEFAULT_INSTRUMENTS = tuple(item.instrument for item in ASSETS)
