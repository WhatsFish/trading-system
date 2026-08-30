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
            details = "; ".join(
                f"{row.get('sCode')}: {row.get('sMsg')}"
                for row in payload.get("data", [])
                if row.get("sCode") or row.get("sMsg")
            )
            raise OkxError(
                f"{method} {path}: {payload.get('code')} {payload.get('msg')}"
                + (f" ({details})" if details else "")
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

    def tickers(self, instrument_type: str = "SWAP") -> dict[str, dict]:
        rows = self.request(
            "GET",
            "/api/v5/market/tickers",
            {"instType": instrument_type},
        )
        return {row["instId"]: row for row in rows}

    def instrument(self, instrument: str) -> dict:
        return self.request(
            "GET",
            "/api/v5/public/instruments",
            {"instType": "SWAP", "instId": instrument},
        )[0]

    def instruments(self, instrument_type: str = "SWAP") -> dict[str, dict]:
        rows = self.request(
            "GET",
            "/api/v5/public/instruments",
            {"instType": instrument_type},
        )
        return {row["instId"]: row for row in rows}

    def account_balance(self) -> dict:
        return self.request("GET", "/api/v5/account/balance", private=True)[0]

    def positions(self) -> list[dict]:
        return self.request("GET", "/api/v5/account/positions", private=True)

    def place_order(self, order: dict) -> dict:
        rows = self.request(
            "POST", "/api/v5/trade/order", body=order, private=True
        )
        if not rows or rows[0].get("sCode") != "0":
            result = rows[0] if rows else {}
            raise OkxError(
                f"order rejected: {result.get('sCode')} {result.get('sMsg')}"
            )
        return rows[0]

    def cancel_order(self, instrument: str, order_id: str) -> dict:
        rows = self.request(
            "POST",
            "/api/v5/trade/cancel-order",
            body={"instId": instrument, "ordId": order_id},
            private=True,
        )
        if not rows or rows[0].get("sCode") != "0":
            result = rows[0] if rows else {}
            raise OkxError(
                f"cancel rejected: {result.get('sCode')} {result.get('sMsg')}"
            )
        return rows[0]

    def order(self, instrument: str, order_id: str) -> dict:
        rows = self.request(
            "GET",
            "/api/v5/trade/order",
            params={"instId": instrument, "ordId": order_id},
            private=True,
        )
        if not rows:
            raise OkxError("order query returned no data")
        return rows[0]

    def order_by_client_id(self, instrument: str, client_order_id: str) -> dict:
        rows = self.request(
            "GET",
            "/api/v5/trade/order",
            params={"instId": instrument, "clOrdId": client_order_id},
            private=True,
        )
        if not rows:
            raise OkxError("client order query returned no data")
        return rows[0]

    def set_leverage(
        self, instrument: str, leverage: str = "1", position_side: str = "long"
    ) -> dict:
        rows = self.request(
            "POST",
            "/api/v5/account/set-leverage",
            body={
                "instId": instrument,
                "lever": leverage,
                "mgnMode": "isolated",
                "posSide": position_side,
            },
            private=True,
        )
        if not rows:
            raise OkxError("set leverage returned no data")
        return rows[0]

    def place_stop(
        self,
        instrument: str,
        size: str,
        trigger_price: str,
        client_order_id: str,
    ) -> dict:
        rows = self.request(
            "POST",
            "/api/v5/trade/order-algo",
            body={
                "instId": instrument,
                "tdMode": "isolated",
                "side": "sell",
                "posSide": "long",
                "ordType": "conditional",
                "sz": size,
                "slTriggerPx": trigger_price,
                "slOrdPx": "-1",
                "algoClOrdId": client_order_id,
                "reduceOnly": True,
            },
            private=True,
        )
        if not rows or rows[0].get("sCode") != "0":
            result = rows[0] if rows else {}
            raise OkxError(
                f"stop rejected: {result.get('sCode')} {result.get('sMsg')}"
            )
        return rows[0]

    def algo_order(self, algo_id: str) -> dict:
        rows = self.request(
            "GET",
            "/api/v5/trade/order-algo",
            params={"algoId": algo_id},
            private=True,
        )
        if not rows:
            raise OkxError("algo order query returned no data")
        return rows[0]

    def algo_order_by_client_id(
        self, instrument: str, client_order_id: str
    ) -> dict:
        rows = self.request(
            "GET",
            "/api/v5/trade/order-algo",
            params={
                "instId": instrument,
                "algoClOrdId": client_order_id,
            },
            private=True,
        )
        if not rows:
            raise OkxError("algo client order query returned no data")
        return rows[0]

    def cancel_algo(self, instrument: str, algo_id: str) -> dict:
        rows = self.request(
            "POST",
            "/api/v5/trade/cancel-algos",
            body=[{"instId": instrument, "algoId": algo_id}],
            private=True,
        )
        if not rows or rows[0].get("sCode") != "0":
            result = rows[0] if rows else {}
            raise OkxError(
                f"algo cancel rejected: {result.get('sCode')} {result.get('sMsg')}"
            )
        return rows[0]
