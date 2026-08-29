import { Pool, type QueryResultRow } from "pg";

const pool = new Pool({
  host: process.env.PG_HOST ?? "db",
  port: parseInt(process.env.PG_PORT ?? "5432", 10),
  user: process.env.PG_USER ?? "trading_system",
  password: process.env.TRADING_PG_PASSWORD,
  database: process.env.PG_DB ?? "trading_system",
  max: 5,
});

export async function query<T extends QueryResultRow>(
  sql: string,
  values: unknown[] = [],
): Promise<T[]> {
  const result = await pool.query<T>(sql, values);
  return result.rows;
}

