import { NextRequest, NextResponse } from "next/server";

function unauthorized() {
  return new NextResponse("Authentication required", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="Trading System"' },
  });
}

export function middleware(request: NextRequest) {
  if (request.nextUrl.pathname.endsWith("/api/health")) {
    return NextResponse.next();
  }
  const expectedUser = process.env.DASHBOARD_USER;
  const expectedPassword = process.env.DASHBOARD_PASSWORD;
  if (!expectedUser || !expectedPassword) {
    return new NextResponse("Dashboard authentication is not configured", {
      status: 503,
    });
  }
  const header = request.headers.get("authorization");
  if (!header?.startsWith("Basic ")) return unauthorized();
  try {
    const [user, password] = atob(header.slice(6)).split(":", 2);
    if (user === expectedUser && password === expectedPassword) {
      return NextResponse.next();
    }
  } catch {
    return unauthorized();
  }
  return unauthorized();
}

