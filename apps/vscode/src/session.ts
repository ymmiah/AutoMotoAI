// Finding the local AutoMoto server and its per-launch token.
//
// `python -m automoto serve` writes <data dir>/session.json (readable by this user only) with
// {url, port, token, pid, version}. The token never goes anywhere except that loopback URL.
import * as fs from "fs";
import * as os from "os";
import * as path from "path";

export interface Session {
  url: string;
  token: string;
  version?: string;
  pid?: number;
}

export class SessionError extends Error {}

export function dataDir(configured?: string, env: NodeJS.ProcessEnv = process.env): string {
  const raw = (configured && configured.trim()) || env.AUTOMOTO_DATA_DIR || path.join(os.homedir(), ".automoto");
  return raw.startsWith("~") ? path.join(os.homedir(), raw.slice(1)) : raw;
}

/** Only plain-http loopback URLs: the token must never leave this computer. */
export function checkLoopback(url: string): string {
  let u: URL;
  try {
    u = new URL(url);
  } catch {
    throw new SessionError(`not a URL: ${url}`);
  }
  const host = u.hostname.replace(/^\[|\]$/g, "");
  if (u.protocol !== "http:" || !["127.0.0.1", "localhost", "::1"].includes(host)) {
    throw new SessionError("AutoMoto's server URL must be http://127.0.0.1:<port> (or localhost) - the session token never leaves this computer");
  }
  if (u.username || u.password) throw new SessionError("server URL must not contain credentials");
  return `${u.protocol}//${u.host}/`;
}

export function readSession(opts: { dataDir?: string; serverUrl?: string } = {}): Session {
  const file = path.join(dataDir(opts.dataDir), "session.json");
  let raw: string;
  try {
    raw = fs.readFileSync(file, "utf8");
  } catch {
    throw new SessionError("AutoMoto isn't running. Start it in a terminal with `python -m automoto serve` (in the AutoMotoAI folder).");
  }
  let data: any;
  try {
    data = JSON.parse(raw);
  } catch {
    throw new SessionError(`can't read ${file}`);
  }
  if (typeof data?.token !== "string" || data.token.length < 20 || typeof data?.url !== "string") {
    throw new SessionError(`${file} is incomplete - restart \`python -m automoto serve\``);
  }
  const url = checkLoopback(opts.serverUrl && opts.serverUrl.trim() ? opts.serverUrl : data.url);
  return { url, token: data.token, version: data.version, pid: data.pid };
}
