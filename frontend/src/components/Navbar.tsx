import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuthStore } from '../stores/authStore';
import { APP_NAME } from '../constants/branding';

const primaryNavLinks = [
  { to: '/goals', label: 'Goals' },
  { to: '/chat', label: 'Chat' },
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/plan', label: 'Plan' },
  { to: '/history', label: 'History' },
  { to: '/menu', label: 'Menu' },
  { to: '/specialists', label: 'Specialists' },
  { to: '/settings', label: 'Settings' },
];

const secondaryNavLinks = [
  { to: '/feedback', label: 'Feedback' },
];

export default function Navbar() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const { user, logout } = useAuthStore();
  const location = useLocation();

  const isActive = (path: string) => location.pathname === path;

  return (
    <nav className="bg-slate-800 border-b border-slate-700 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-14">
          {/* Logo */}
            <Link to="/goals" className="flex items-center gap-2 shrink-0">
            <span className="text-emerald-500 font-bold text-lg">{APP_NAME}</span>
            </Link>

          {/* Desktop nav links */}
          <div className="hidden md:flex items-center gap-1">
            {primaryNavLinks.map((link) => (
              <Link
                key={link.to}
                to={link.to}
                className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  isActive(link.to)
                    ? 'bg-slate-700 text-emerald-400'
                    : 'text-slate-300 hover:bg-slate-700 hover:text-white'
                }`}
              >
                {link.label}
              </Link>
            ))}
          </div>

          {/* User section (desktop) */}
          <div className="hidden md:flex items-center gap-3">
            {secondaryNavLinks.map((link) => (
              <Link
                key={link.to}
                to={link.to}
                className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  isActive(link.to)
                    ? 'bg-slate-700 text-emerald-400'
                    : 'text-slate-300 hover:bg-slate-700 hover:text-white'
                }`}
              >
                {link.label}
              </Link>
            ))}
            <span className="text-sm text-slate-300">
              {user?.display_name || user?.username}
            </span>
            <button
              onClick={logout}
              className="px-3 py-1.5 text-sm text-slate-300 hover:text-white bg-slate-700 hover:bg-slate-600 rounded-md transition-colors"
            >
              Logout
            </button>
          </div>

          {/* Mobile hamburger */}
          <button
            onClick={() => setMobileOpen(!mobileOpen)}
            className="md:hidden p-2 rounded-md text-slate-400 hover:text-white hover:bg-slate-700 transition-colors"
            aria-label="Toggle menu"
          >
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              {mobileOpen ? (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              ) : (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              )}
            </svg>
          </button>
        </div>
      </div>

      {/* Mobile menu */}
      {mobileOpen && (
        <div className="md:hidden border-t border-slate-700">
          <div className="px-2 pt-2 pb-3 space-y-1">
            {[...primaryNavLinks, ...secondaryNavLinks].map((link) => (
              <Link
                key={link.to}
                to={link.to}
                onClick={() => setMobileOpen(false)}
                className={`block px-3 py-2 rounded-md text-base font-medium transition-colors ${
                  isActive(link.to)
                    ? 'bg-slate-700 text-emerald-400'
                    : 'text-slate-300 hover:bg-slate-700 hover:text-white'
                }`}
              >
                {link.label}
              </Link>
            ))}
          </div>
          <div className="border-t border-slate-700 px-4 py-3 flex items-center justify-between">
            <span className="text-sm text-slate-300">
              {user?.display_name || user?.username}
            </span>
            <button
              onClick={() => { logout(); setMobileOpen(false); }}
              className="px-3 py-1.5 text-sm text-slate-300 hover:text-white bg-slate-700 hover:bg-slate-600 rounded-md transition-colors"
            >
              Logout
            </button>
          </div>
        </div>
      )}
    </nav>
  );
}
