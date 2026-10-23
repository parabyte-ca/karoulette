// Sign the host in once for the whole run (the server allows only a few logins a minute) and save the
// session cookie for the tests to reuse.
import { request } from "@playwright/test";

export default async function globalSetup(config) {
  const { baseURL } = config.projects[0].use;
  const ctx = await request.newContext({ baseURL });
  const res = await ctx.post("/api/host/login", { data: { pin: "2468" } });
  if (!res.ok()) throw new Error(`Host login failed: ${res.status()}`);
  await ctx.storageState({ path: "e2e/.data/host.json" });
  await ctx.dispose();
}
