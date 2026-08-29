import { query } from "@/lib/db";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const rows = await query<{ last_seen_at: Date; status: string }>(
      "SELECT last_seen_at, status FROM worker_heartbeat WHERE worker = 'collector'",
    );
    if (!rows.length) {
      return Response.json({ ok: false, reason: "no heartbeat" }, { status: 503 });
    }
    const ageMs = Date.now() - new Date(rows[0].last_seen_at).getTime();
    const ok = rows[0].status === "ok" && ageMs < 180_000;
    return Response.json(
      { ok, workerStatus: rows[0].status, heartbeatAgeSeconds: Math.floor(ageMs / 1000) },
      { status: ok ? 200 : 503 },
    );
  } catch (error) {
    return Response.json(
      { ok: false, error: error instanceof Error ? error.message : "unknown error" },
      { status: 503 },
    );
  }
}

