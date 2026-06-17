import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'AI Opportunity Radar',
  description: 'B2B buying intent intelligence for AI automation agencies',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-[#0f1117] text-slate-200 antialiased min-h-screen">
        <nav className="border-b border-slate-800 px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center">
              <span className="text-white text-xs font-bold">R</span>
            </div>
            <span className="font-semibold text-white tracking-tight">Opportunity Radar</span>
          </div>
          <nav className="flex items-center gap-6 text-sm text-slate-400">
            <a href="/" className="hover:text-white transition-colors">Feed</a>
            <a href="/analytics" className="hover:text-white transition-colors">Analytics</a>
            <a href="/settings" className="hover:text-white transition-colors">Settings</a>
          </nav>
        </nav>
        <main className="max-w-6xl mx-auto px-6 py-8">
          {children}
        </main>
      </body>
    </html>
  )
}
