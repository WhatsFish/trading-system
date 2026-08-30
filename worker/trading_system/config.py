from dataclasses import dataclass
from decimal import Decimal
import os

from .universe import DEFAULT_INSTRUMENTS


def database_url_from_env() -> str:
    password = os.environ["TRADING_PG_PASSWORD"]
    return (
        f"postgresql://trading_system:{password}@"
        f"{os.getenv('PG_HOST', 'db')}:{os.getenv('PG_PORT', '5432')}/"
        "trading_system"
    )


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
    max_position_pct: Decimal = Decimal("0.35")
    max_total_exposure_pct: Decimal = Decimal("1.50")
    max_leverage: Decimal = Decimal("1")
    daily_loss_pct: Decimal = Decimal("0.10")
    max_drawdown_pct: Decimal = Decimal("0.20")
    max_basis_bps: Decimal = Decimal("100")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            okx_key=os.environ["OKX_API_KEY"],
            okx_secret=os.environ["OKX_API_SECRET"],
            okx_passphrase=os.environ["OKX_API_PASSPHRASE"],
            database_url=database_url_from_env(),
            mode=os.getenv("TRADING_MODE", "observe"),
            live_ack=os.getenv("LIVE_TRADING_ACK", ""),
            instruments=tuple(
                item.strip()
                for item in os.getenv(
                    "TRADING_INSTRUMENTS",
                    ",".join(DEFAULT_INSTRUMENTS),
                ).split(",")
                if item.strip()
            ),
            poll_seconds=int(os.getenv("POLL_SECONDS", "60")),
        )
