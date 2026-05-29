import type { Metadata } from 'next'
import { Geist } from 'next/font/google'
import Link from 'next/link'
import './globals.css'

const geist = Geist({ subsets: ['latin'], variable: '--font-geist-sans' })

export const metadata: Metadata = {
  title: 'SJ House Buyers — Command',
  description: 'San Joaquin House Buyers Acquisition Operations',
}

const NAV = [
  { href: '/', label: 'Command', icon: '⬡' },
  { href: '/calls', label: 'Calls', icon: '◎' },
  { href: '/leads', label: 'Pipeline', icon: '◈' },
  { href: '/analytics', label: 'Analytics', icon: '◻' },
  { href: '/settings', label: 'Settings', icon: '◌' },
]

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={geist.variable}>
      <body className="flex h-screen overflow-hidden" style={{ background: 'var(--bg)' }}>

        {/* Sidebar */}
        <aside className="w-48 shrink-0 flex flex-col border-r" style={{ borderColor: 'var(--border)', background: 'var(--bg-card)' }}>
          {/* Logo */}
          <div className="px-4 py-5 border-b" style={{ borderColor: 'var(--border)' }}>
            <p className="text-xs font-semibold tracking-widest uppercase" style={{ color: 'var(--text-dim)' }}>SJ House Buyers</p>
            <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>Acquisitions Ops</p>
          </div>

          {/* Nav */}
          <nav className="flex-1 py-3">
            {NAV.map(({ href, label, icon }) => (
              <Link
                key={href}
                href={href}
                className="flex items-center gap-3 px-4 py-2.5 text-sm transition-colors hover:text-white"
                style={{ color: 'var(--text-dim)' }}
              >
                <span style={{ color: 'var(--teal)' }}>{icon}</span>
                {label}
              </Link>
            ))}
          </nav>

          {/* Bottom */}
          <div className="px-4 py-4 border-t text-xs" style={{ borderColor: 'var(--border)', color: 'var(--text-muted)' }}>
            <div className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
              Sophia active
            </div>
          </div>
        </aside>

        {/* Main */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Top bar */}
          <header className="h-12 shrink-0 flex items-center justify-between px-6 border-b" style={{ borderColor: 'var(--border)', background: 'var(--bg-card)' }}>
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
              {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
            </p>
            <div className="flex items-center gap-4">
              <a href="/leads/new" className="text-xs px-3 py-1.5 rounded font-medium transition-colors" style={{ background: 'var(--teal)', color: 'var(--bg)' }}>
                + New Lead
              </a>
            </div>
          </header>

          {/* Page content */}
          <main className="flex-1 overflow-y-auto">
            {children}
          </main>
        </div>
      </body>
    </html>
  )
}
