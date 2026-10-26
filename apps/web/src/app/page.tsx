"use client";
import {FormEvent, useEffect, useState} from "react";
type User = {id: string; name: string; email: string; role: string; tenant_id: string | null};
export default function Home() {
  const [user, setUser] = useState<User | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {fetch("/api/v1/users/me").then(async r => {if (r.ok) setUser(await r.json());}).catch(() => setMessage("Unable to reach the API."));}, []);
  async function login(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); setBusy(true); setMessage("");
    const form = e.currentTarget; const data = new FormData(form);
    try {
      const response = await fetch("/api/v1/auth/login", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({email:data.get("email"), password:data.get("password")})});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error?.message || "Sign in failed");
      setUser(result.user); form.reset();
    } catch (error) {setMessage(error instanceof Error ? error.message : "Sign in failed");}
    finally {setBusy(false);}
  }
  async function logout() {
    setBusy(true);
    try {
      const result = await fetch("/api/v1/auth/logout", {method:"POST"});
      if (!result.ok) throw new Error("Unable to sign out");
      setUser(null); setMessage("");
    } catch {setMessage("Unable to sign out. Please try again.");}
    finally {setBusy(false);}
  }
  return <main className="mx-auto max-w-lg px-6 py-20">
    <p className="text-sm font-semibold uppercase tracking-widest text-teal-700">SomaLoom</p>
    <h1 className="mt-3 text-3xl font-semibold">Educational content intelligence</h1>
    <p className="mt-4 text-slate-600">Secure platform foundation. Content tools are being integrated.</p>
    {user ? <section className="mt-8 rounded-xl border border-slate-200 bg-white p-6" aria-label="Your account">
      <h2 className="text-xl font-semibold">Welcome, {user.name}</h2><p className="mt-2">{user.email}</p><p className="mt-2 text-slate-600">Role: {user.role}</p>
      <button disabled={busy} onClick={logout} className="mt-6 rounded-lg bg-slate-900 px-5 py-3 text-white disabled:opacity-50">Sign out</button>
    </section> : <form onSubmit={login} className="mt-8 grid gap-4 rounded-xl border border-slate-200 bg-white p-6">
      <h2 className="text-xl font-semibold">Sign in</h2>
      <label className="grid gap-2">Email<input className="rounded-md border border-slate-300 p-3" name="email" type="email" autoComplete="username" required maxLength={320}/></label>
      <label className="grid gap-2">Password<input className="rounded-md border border-slate-300 p-3" name="password" type="password" autoComplete="current-password" required maxLength={1024}/></label>
      <button disabled={busy} className="rounded-lg bg-teal-700 p-3 font-medium text-white disabled:opacity-50">{busy ? "Signing in…" : "Sign in"}</button>
      <p className="text-sm text-slate-500">Ask your school administrator for an account.</p>
    </form>}
    <p role="status" aria-live="polite" className="mt-4 text-red-700">{message}</p>
  </main>;
}
