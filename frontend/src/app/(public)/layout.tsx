export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return (
    <main id="main" className="flex min-h-screen items-start justify-center px-4 py-12 sm:items-center">
      <div className="w-full max-w-md">
        <p className="mb-6 text-center text-2xl font-bold tracking-tight text-emerald-800">ShopFlow</p>
        <div className="rounded-lg bg-white p-6 shadow-sm ring-1 ring-slate-200 sm:p-8">{children}</div>
      </div>
    </main>
  );
}
