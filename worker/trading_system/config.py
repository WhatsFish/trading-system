from dataclasses import dataclass
from decimal import Decimal
import os


@dataclass(frozen=True)
class Settings:
    okx_key: str
    okx_secret: str
    okx_passphrase: str
    database_url: str
    mode: str
    live_ack: str
    instruments: tuple[str, ...]
    poll_seconds: int
    max_position_pct: Decimal = Decimal("0.20")
    max_total_exposure_pct: Decimal = Decimal("0.50")
    max_leverage: Decimal = Decimal("2")
    daily_loss_pct: Decimal = Decimal("0.02")
    max_drawdown_pct: Decimal = Decimal("0.05")

    @classmethod
    def from_env(cls) -> "Settings":
        password = os.environ["TRADING_PG_PASSWORD"]
        return cls(
            okx_key=os.environ["OKX_API_KEY"],
            okx_secret=os.environ["OKX_API_SECRET"],
            okx_passphrase=os.environ["OKX_API_PASSPHRASE"],
            database_url=(
                f"postgresql://trading_system:{password}@"
                f"{os.getenv('PG_HOST', 'db')}:{os.getenv('PG_PORT', '5432')}/"
                "trading_system"
            ),
            mode=os.getenv("TRADING_MODE", "observe"),
            live_ack=os.getenv("LIVE_TRADING_ACK", ""),
            instruments=tuple(
                item.strip()
                for item in os.getenv(
                    "TRADING_INSTRUMENTS",
                    "BTC-USDT-SWAP,ETH-USDT-SWAP,SOL-USDT-SWAP",
                ).split(",")
                if item.strip()
            ),
            poll_seconds=int(os.getenv("POLL_SECONDS", "60")),
        )

