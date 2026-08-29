import base64
import datetime as dt
import hashlib
import hmac
import json
import urllib.error
import urllib.parse
import urllib.request


class OkxError(RuntimeError):
    pass


class OkxClient:
    base_url = "https://www.okx.com"

    def __init__(self, key: str, secret: str, passphrase: str) -> None:
        self.key = key
        self.secret = secret
        self.passphrase = passphrase

    def request(
        self,
        method: str,
        path: str,
        params: dict[str, str] | None = None,
        body: dict | None = None,
        private: bool = False,
    ) -> list[dict]:
        if params:
            path += "?" + urllib.parse.urlencode(params)
        encoded = (
            json.dumps(body, separators=(",", ":")).encode() if body is not None else None
        )
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "trading-system/0.1",
        }
        if private:
            timestamp = (
                dt.datetime.now(dt.timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z")
            )
            prehash = f"{timestamp}{method}{path}" + (
                encoded.decode() if encoded else ""
            )
            signature = base64.b64encode(
                hmac.new(
                    self.secret.encode(), prehash.encode(), hashlib.sha256
                ).digest()
            ).decode()
            headers.update(
                {
                    "OK-ACCESS-KEY": self.key,
                    "OK-ACCESS-SIGN": signature,
                    "OK-ACCESS-TIMESTAMP": timestamp,
                    "OK-ACCESS-PASSPHRASE": self.passphrase,
                }
            )
        request = urllib.request.Request(
            self.base_url + path,
            data=encoded,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            try:
                payload = json.load(error)
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise OkxError(f"HTTP {error.code}: {error.reason}") from error
        if payload.get("code") != "0":
            raise OkxError(
                f"{method} {path}: {payload.get('code')} {payload.get('msg')}"
            )
        return payload.get("data", [])

    def candles(self, instrument: str, limit: int = 100) -> list[dict]:
        rows = self.request(
            "GET",
            "/api/v5/market/candles",
            {"instId": instrument, "bar": "5m", "limit": str(limit)},
        )
        return [
            {
                "ts": int(row[0]),
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
                "volume": row[5],
                "confirmed": row[8] == "1",
            }
            for row in rows
        ]

    def historical_candles(
        self, instrument: str, after: int | None = None, limit: int = 100
    ) -> list[dict]:
        params = {"instId": instrument, "bar": "5m", "limit": str(limit)}
        if after is not None:
            params["after"] = str(after)
        rows = self.request("GET", "/api/v5/market/history-candles", params)
        return [
            {
                "ts": int(row[0]),
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
                "volume": row[5],
                "confirmed": row[8] == "1",
            }
            for row in rows
        ]

    def ticker(self, instrument: str) -> dict:
        return self.request(
            "GET", "/api/v5/market/ticker", {"instId": instrument}
        )[0]

    def instrument(self, instrument: str) -> dict:
        return self.request(
            "GET",
            "/api/v5/public/instruments",
            {"instType": "SWAP", "instId": instrument},
        )[0]

    def account_balance(self) -> dict:
        return self.request("GET", "/api/v5/account/balance", private=True)[0]

    def positions(self) -> list[dict]:
        return self.request("GET", "/api/v5/account/positions", private=True)
