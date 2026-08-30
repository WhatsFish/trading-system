import json
import uuid
import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

from .config import database_url_from_env
from .research_backtest import evaluate
from .strategy_library import strategy_specs
from .universe import ASSETS


FOLDS = ((0.50, 0.66), (0.66, 0.83), (0.83, 1.0))
ROUND_TRIP_SIDE_COST = Decimal("0.0015")


def completed_session_cutoff(
    now: dt.datetime | None = None,
) -> dt.date:
    eastern = (now or dt.datetime.now(dt.timezone.utc)).astimezone(
        ZoneInfo("America/New_York")
    )
    if eastern.weekday() < 5 and eastern.time() < dt.time(16, 15):
        return eastern.date() - dt.timedelta(days=1)
    return eastern.date()


def fold_results(
    execution_prices: list[Decimal], desired: list[int]
) -> list:
    results = []
    for start_fraction, end_fraction in FOLDS:
        start = int(len(execution_prices) * start_fraction)
        end = int(len(execution_prices) * end_fraction)
        results.append(
            evaluate(
                execution_prices[start - 1 : end],
                desired[start - 1 : end],
                ROUND_TRIP_SIDE_COST,
            )
        )
    return results


def rows_to_bars(rows: list[tuple]) -> list[dict]:
    return [
        {
            "date": row[0],
            "open": str(row[1]),
            "high": str(row[2]),
            "low": str(row[3]),
            "close": str(row[4]),
            "volume": str(row[5] or 0),
        }
        for row in rows
    ]


def main() -> None:
    import psycopg
    import pandas as pd
    from psycopg.types.json import Jsonb
    from .strategy_vectorized import generate_targets_vectorized

    run_id = uuid.uuid4()
    specs = strategy_specs()
    cutoff = completed_session_cutoff()
    with psycopg.connect(database_url_from_env()) as connection:
        benchmark_rows = connection.execute(
            """
            SELECT date, open, high, low, close, volume
            FROM underlying_daily
            WHERE symbol = 'SPY' AND date <= %s ORDER BY date
            """,
            (cutoff,),
        ).fetchall()
        benchmark_by_date = {
            row[0]: {
                "date": row[0],
                "open": str(row[1]),
                "high": str(row[2]),
                "low": str(row[3]),
                "close": str(row[4]),
                "volume": str(row[5] or 0),
            }
            for row in benchmark_rows
        }

        for asset in ASSETS:
            symbol = asset.instrument.split("-", 1)[0]
            rows = connection.execute(
                """
                SELECT date, open, high, low, close, volume
                FROM underlying_daily
                WHERE symbol = %s AND date <= %s ORDER BY date
                """,
                (symbol, cutoff),
            ).fetchall()
            bars = rows_to_bars(rows)
            if len(bars) < 504:
                continue
            frame = pd.DataFrame(bars)
            frame.index = pd.to_datetime(frame.pop("date"))
            frame = frame.astype(float)
            benchmark = pd.Series(
                [
                    float(benchmark_by_date.get(row["date"], row)["close"])
                    for row in bars
                ],
                index=frame.index,
            )
            execution_prices = [Decimal(row["open"]) for row in bars]
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

            for spec in specs:
                signals = generate_targets_vectorized(frame, spec, benchmark)
                # A close-derived signal is executable no earlier than the next open.
                desired = [0] + signals[:-1].tolist()
                folds = fold_results(execution_prices, desired)
                compounded = Decimal("1")
                for result in folds:
                    compounded *= Decimal("1") + result.return_pct / Decimal("100")
                total_return = (compounded - 1) * 100
                max_drawdown = max(result.drawdown_pct for result in folds)
                trades = sum(result.trades for result in folds)
                positive = sum(result.return_pct > 0 for result in folds)
                validation_compounded = Decimal("1")
                for result in folds[:2]:
                    validation_compounded *= (
                        Decimal("1") + result.return_pct / Decimal("100")
                    )
                validation_return = (validation_compounded - 1) * 100
                validation_drawdown = max(
                    result.drawdown_pct for result in folds[:2]
                )
                validation_trades = sum(result.trades for result in folds[:2])
                historical_score = (
                    validation_return - Decimal("2") * validation_drawdown
                )
                holdout = folds[2]
                experience_count, live_average, live_loss_rate = live_experience.get(
                    spec.name, (0, Decimal("0"), Decimal("0"))
                )
                live_adjustment = Decimal("0")
                if experience_count >= 5:
                    weight = min(
                        Decimal("1"),
                        Decimal(experience_count) / Decimal("20"),
                    )
                    live_adjustment = weight * (
                        live_average - live_loss_rate * Decimal("2")
                    )
                score = historical_score + live_adjustment
                reasons = []
                if sum(result.return_pct > 0 for result in folds[:2]) < 1:
                    reasons.append("no_positive_validation_fold")
                if validation_trades < 4:
                    reasons.append("insufficient_validation_trades")
                if validation_drawdown > 20:
                    reasons.append("validation_drawdown_above_20pct")
                if score <= 0:
                    reasons.append("non_positive_validation_score")
                connection.execute(
                    """
                    INSERT INTO strategy_experiment
                      (run_id, symbol, family, cluster, parameters, fold_returns,
                       return_pct, drawdown_pct, trades, positive_folds,
                       current_target, score, live_experience_count,
                       live_adjustment, validation_score,
                       holdout_return_pct, holdout_drawdown_pct,
                       holdout_trades, eligible, rejection_reason)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        run_id,
                        symbol,
                        spec.name,
                        spec.cluster,
                        Jsonb(spec.parameters),
                        Jsonb([str(result.return_pct) for result in folds]),
                        total_return,
                        max_drawdown,
                        trades,
                        positive,
                        int(signals[-1]),
                        score,
                        experience_count,
                        live_adjustment,
                        historical_score,
                        holdout.return_pct,
                        holdout.drawdown_pct,
                        holdout.trades,
                        not reasons,
                        ",".join(reasons) or None,
                    ),
                )
                parameter_key = json.dumps(
                    spec.parameters, sort_keys=True, separators=(",", ":")
                )
                connection.execute(
                    """
                    INSERT INTO strategy_live_target
                      (symbol, family, parameter_key, parameters, current_target)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (symbol, family, parameter_key) DO UPDATE SET
                      parameters = EXCLUDED.parameters,
                      current_target = EXCLUDED.current_target,
                      computed_at = NOW()
                    """,
                    (
                        symbol,
                        spec.name,
                        parameter_key,
                        Jsonb(spec.parameters),
                        int(signals[-1]),
                    ),
                )

        connection.execute(
            """
            WITH ranked AS (
              SELECT id, symbol, family, score, holdout_return_pct,
                     holdout_drawdown_pct, holdout_trades,
                     ROW_NUMBER() OVER (
                       PARTITION BY symbol, family ORDER BY score DESC
                     ) AS parameter_rank
              FROM strategy_experiment
              WHERE run_id = %s AND eligible
            )
            INSERT INTO strategy_candidate
              (symbol, family, experiment_id, score)
            SELECT symbol, family, id,
                   score
            FROM ranked
            WHERE parameter_rank = 1
              AND holdout_return_pct > 0
              AND holdout_drawdown_pct <= 20
              AND holdout_trades >= 1
              AND holdout_return_pct - 2 * holdout_drawdown_pct > 0
            ON CONFLICT (symbol, family) DO UPDATE SET
              experiment_id = EXCLUDED.experiment_id,
              score = EXCLUDED.score,
              promoted_at = NOW()
            """,
            (run_id,),
        )
        connection.execute(
            """
            DELETE FROM strategy_candidate c
            USING strategy_experiment e
            WHERE c.experiment_id = e.id AND e.run_id <> %s
            """,
            (run_id,),
        )
        connection.commit()
        summary = connection.execute(
            """
            SELECT COUNT(*), COUNT(*) FILTER (WHERE eligible),
                   COUNT(DISTINCT family)
            FROM strategy_experiment WHERE run_id = %s
            """,
            (run_id,),
        ).fetchone()
    print(
        f"strategy lab run={run_id} experiments={summary[0]} "
        f"eligible={summary[1]} families={summary[2]}"
    )


if __name__ == "__main__":
    main()
