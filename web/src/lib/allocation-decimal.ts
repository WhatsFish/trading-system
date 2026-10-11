// Exact decimal fractions keep proportional shares and lot floors below their budgets.
export type Decimal = { n: bigint; d: bigint };
const zero = BigInt(0);
const one = BigInt(1);
function power10(exponent: number): bigint {
  let result = one;
  for (let i = 0; i < exponent; i++) result *= BigInt(10);
  return result;
}
export function decimal(value: string | number): Decimal {
  const match = /^([+-]?)(\d+)(?:\.(\d*))?(?:e([+-]?\d+))?$/i.exec(String(value));
  if (!match) throw new Error("invalid_decimal");
  const scale = (match[3]?.length ?? 0) - Number(match[4] ?? 0);
  if (Math.abs(scale) > 100) throw new Error("invalid_decimal_scale");
  let n = BigInt(match[2] + (match[3] ?? "")) * (match[1] === "-" ? -one : one);
  let d = one;
  if (scale > 0) d = power10(scale);
  else n *= power10(-scale);
  return { n, d };
}
export const add = (a: Decimal, b: Decimal): Decimal => ({ n: a.n * b.d + b.n * a.d, d: a.d * b.d });
export const sub = (a: Decimal, b: Decimal): Decimal => ({ n: a.n * b.d - b.n * a.d, d: a.d * b.d });
export const mul = (a: Decimal, b: Decimal): Decimal => ({ n: a.n * b.n, d: a.d * b.d });
export function div(a: Decimal, b: Decimal): Decimal {
  if (b.n <= zero) throw new Error("invalid_divisor");
  return { n: a.n * b.d, d: a.d * b.n };
}
export const compare = (a: Decimal, b: Decimal) => a.n * b.d < b.n * a.d ? -1 : a.n * b.d > b.n * a.d ? 1 : 0;
export const min = (a: Decimal, b: Decimal) => compare(a, b) <= 0 ? a : b;
export const positive = (a: Decimal) => compare(a, decimal(0)) > 0 ? a : decimal(0);
export function floorLot(quantity: Decimal, lot: Decimal): Decimal {
  const ratio = div(quantity, lot);
  return mul(decimal(String(ratio.n / ratio.d)), lot);
}
export function text(value: Decimal, places = 12): string {
  const scale = power10(places);
  const units = value.n * scale / value.d;
  const negative = units < zero;
  const digits = (negative ? -units : units).toString().padStart(places + 1, "0");
  const result = places ? `${digits.slice(0, -places)}.${digits.slice(-places)}`.replace(/\.?0+$/, "") : digits;
  return (negative ? "-" : "") + result;
}
