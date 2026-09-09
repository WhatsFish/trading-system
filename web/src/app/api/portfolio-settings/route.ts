import { NextResponse } from "next/server";
import { pool } from "@/lib/db";
import { authorize } from "@/lib/portfolio-auth";
import { PortfolioError } from "@/lib/portfolio";
import { confirmPreview, createPreview, inTransaction, overview } from "@/lib/portfolio-store";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
const headers = { "Cache-Control": "no-store" };
function failure(error: unknown) {
  if (error instanceof PortfolioError) return NextResponse.json({ error: error.message }, {
    status: error.status, headers: { ...headers, ...(error.status === 401 ? { "WWW-Authenticate": 'Basic realm="Trading System"' } : {}) },
  });
  // Do not return database messages, connection strings or credentials.
  console.error("Portfolio settings request failed", error instanceof Error ? error.name : "unknown");
  return NextResponse.json({ error: "settings_unavailable" }, { status: 503, headers });
}
export async function GET(request: Request) {
  try {
    authorize(request);
    return NextResponse.json(await overview(pool), { headers });
  } catch (error) { return failure(error); }
}
export async function POST(request: Request) {
  try {
    const actor = authorize(request, true);
    if (Number(request.headers.get("content-length") ?? 0) > 32_768) throw new PortfolioError("body_too_large", 413);
    const text = await request.text();
    if (text.length > 32_768) throw new PortfolioError("body_too_large", 413);
    let body;
    try { body = JSON.parse(text); } catch { throw new PortfolioError("invalid_json"); }
    if (!body || typeof body !== "object" || Array.isArray(body)) throw new PortfolioError("invalid_body");
    if (body.action !== "preview" && body.action !== "confirm") throw new PortfolioError("invalid_action");
    const db = await pool.connect();
    try {
      const result = await inTransaction(db, async () => body.action === "preview"
        ? await createPreview(db, actor, body.config, body.expectedRevision)
        : await confirmPreview(db, actor, body));
      return NextResponse.json(result, { headers });
    } finally { db.release(); }
  } catch (error) { return failure(error); }
}
