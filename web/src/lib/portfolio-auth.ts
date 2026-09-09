import { createHash, timingSafeEqual } from "node:crypto";
import { PortfolioError } from "./portfolio";

function equal(a: string, b: string) {
  return timingSafeEqual(createHash("sha256").update(a).digest(), createHash("sha256").update(b).digest());
}
export function authorize(request: Request, mutation = false): string {
  const user = process.env.DASHBOARD_USER;
  const password = process.env.DASHBOARD_PASSWORD;
  if (!user || !password) throw new PortfolioError("authentication_not_configured", 503);
  const header = request.headers.get("authorization") ?? "";
  if (!/^Basic [A-Za-z0-9+/]+=*$/.test(header)) throw new PortfolioError("authentication_required", 401);
  const decoded = Buffer.from(header.slice(6), "base64").toString("utf8");
  const separator = decoded.indexOf(":");
  if (separator < 0 || !equal(decoded.slice(0, separator), user) || !equal(decoded.slice(separator + 1), password)) throw new PortfolioError("authentication_required", 401);
  if (mutation) {
    const origin = request.headers.get("origin");
    const host = request.headers.get("host");
    const protocol = request.headers.get("x-forwarded-proto") ?? new URL(request.url).protocol.replace(":", "");
    if (!origin || !host || origin !== `${protocol}://${host}` ||
        request.headers.get("sec-fetch-site") === "cross-site") throw new PortfolioError("same_origin_required", 403);
    if (request.headers.get("content-type")?.split(";")[0].trim() !== "application/json") throw new PortfolioError("json_required", 415);
  }
  return user;
}
