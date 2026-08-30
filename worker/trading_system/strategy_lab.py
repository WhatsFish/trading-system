import itertools
import uuid
from decimal import Decimal

from .config import database_url_from_env
from .research_backtest import evaluate, mean
from .universe import ASSETS


FOLDS = ((0.50, 0.66), (0.66, 0.83), (0.83, 1.0))
FEE_RATE = Decimal("0.0015")


def parameter_grid() -> list[tuple[str, dict[str, int | str]]]:
    experiments: list[tuple[str, dict[str, int | str]]] = []
    for fast, slow in itertools.product((10, 20, 30), (50, 100, 150)):
        if fast < slow:
            experiments.append(("trend", {"fast": fast, "slow": slow}))
    for entry, exit_days in itertools.product((10, 20, 40, 60), (5, 10, 20)):
        if exit_days < entry:
            experiments.append(
                ("breakout", {"entryDays": entry, "exitDays": exit_days})
            )
    for lookback, threshold_bps in itertools.product(
        (10, 20, 40), (150, 250, 350, 500)
    ):
        experiments.append(
            (
                "mean-reversion",
                {"lookback": lookback, "thresholdBps": threshold_bps},
            )
        )
    return experiments


def parameter_targets(
    closes: list[Decimal], family: str, parameters: dict[str, int | str]
) -> list[int]:
    output = [0] * len(closes)
    position = 0
    for index, close in enumerate(closes):
        if family == "trend":
            fast = int(parameters["fast"])
            slow = int(parameters["slow"])
            if index >= slow:
                position = int(
                    close > mean(closes[index - fast : index])
                    > mean(closes[index - slow : index])
                )
        elif family == "breakout":
            entry = int(parameters["entryDays"])
            exit_days = int(parameters["exitDays"])
            if index >= entry:
                if not position and close > max(closes[index - entry : index]):
                    position = 1
                elif position and close < min(
                    closes[index - exit_days : index]
                ):
                    position = 0
        elif family == "mean-reversion":
            lookback = int(parameters["lookback"])
            threshold = Decimal(int(parameters["thresholdBps"])) / Decimal("10000")
            if index >= max(lookback, 100):
                average = mean(closes[index - lookback : index])
                regime = close > mean(closes[index - 100 : index])
                if not position and regime and close < average * (1 - threshold):
                    position = 1
                elif position and close >= average:
                    position = 0
        else:
            raise ValueError(f"unknown family: {family}")
        output[index] = position
    return output


def fold_results(
    closes: list[Decimal], desired: list[int]
) -> list:
    results = []
    for start_fraction, end_fraction in FOLDS:
        start = int(len(closes) * start_fraction)
        end = int(len(closes) * end_fraction)
        results.append(
            evaluate(
                closes[start - 1 : end],
                desired[start - 1 : end],
                FEE_RATE,
            )
        )
    return results


def main() -> None:
    import psycopg
    from psycopg.types.json import Jsonb

    run_id = uuid.uuid4()
    grid = parameter_grid()
    with psycopg.connect(database_url_from_env()) as connection:
        for asset in ASSETS:
            symbol = asset.instrument.split("-", 1)[0]
            live_rows = connection.execute(
                """
                SELECT strategy, COUNT(*), AVG(return_pct),
                       AVG(CASE WHEN net_pnl < 0 THEN 1.0 ELSE 0.0 END)
                FROM live_experiment
                WHERE instrument = %s AND status = 'closed'
                GROUP BY strategy
                """,
                (asset.instrument,),
            ).fetchall()
            live_experience = {
                family: (int(count), Decimal(average), Decimal(loss_rate))
                for family, count, average, loss_rate in live_rows
            }
            rows = connection.execute(
                "SELECT close FROM underlying_daily WHERE symbol = %s ORDER BY date",
                (symbol,),
            ).fetchall()
            closes = [Decimal(row[0]) for row in rows]
            if len(closes) < 756:
                continue
            for family, parameters in grid:
                desired = parameter_targets(closes, family, parameters)
                folds = fold_results(closes, desired)
                compounded = Decimal("1")
                for result in folds:
                    compounded *= Decimal("1") + result.return_pct / Decimal("100")
                total_return = (compounded - 1) * 100
                max_drawdown = max(result.drawdown_pct for result in folds)
                trades = sum(result.trades for result in folds)
                positive = sum(result.return_pct > 0 for result in folds)
                historical_score = total_return - Decimal("2") * max_drawdown
                experience_count, live_average, live_loss_rate = live_experience.get(
                    family, (0, Decimal("0"), Decimal("0"))
                )
                live_adjustment = Decimal("0")
                if experience_count >= 5:
                    weight = min(Decimal("1"), Decimal(experience_count) / Decimal("20"))
                    live_adjustment = weight * (
                        live_average - live_loss_rate * Decimal("2")
                    )
                score = historical_score + live_adjustment
                reasons = []
                if positive < 2:
                    reasons.append("fewer_than_two_positive_folds")
                if trades < 6:
                    reasons.append("insufficient_trades")
                if max_drawdown > 15:
                    reasons.append("drawdown_above_15pct")
                if score <= 0:
                    reasons.append("non_positive_risk_score")
                connection.execute(
                    """
                    INSERT INTO strategy_experiment
                      (run_id, symbol, family, parameters, fold_returns,
                       return_pct, drawdown_pct, trades, positive_folds,
                        current_target, score, live_experience_count, live_adjustment,
                        eligible, rejection_reason)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                             %s, %s, %s, %s, %s)
                    """,
                    (
                        run_id,
                        symbol,
                        family,
                        Jsonb(parameters),
                        Jsonb([str(result.return_pct) for result in folds]),
                        total_return,
                        max_drawdown,
                        trades,
                        positive,
                        desired[-1],
                        score,
                        experience_count,
                        live_adjustment,
                        not reasons,
                        ",".join(reasons) or None,
                    ),
                )
        connection.execute(
            """
            INSERT INTO strategy_candidate
              (symbol, family, experiment_id, score)
            SELECT DISTINCT ON (symbol, family)
              symbol, family, id, score
            FROM strategy_experiment
            WHERE run_id = %s AND eligible
            ORDER BY symbol, family, score DESC
            ON CONFLICT (symbol, family) DO UPDATE SET
              experiment_id = EXCLUDED.experiment_id,
              score = EXCLUDED.score,
              promoted_at = NOW()
            """,
            (run_id,),
        )
        connection.commit()
        summary = connection.execute(
            """
            SELECT COUNT(*), COUNT(*) FILTER (WHERE eligible)
            FROM strategy_experiment WHERE run_id = %s
            """,
            (run_id,),
        ).fetchone()
    print(f"strategy lab run={run_id} experiments={summary[0]} eligible={summary[1]}")


if __name__ == "__main__":
    main()
