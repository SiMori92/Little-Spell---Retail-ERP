'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState } from 'react';
import { House, ShoppingBag, Truck, Package, Wallet, LockKeyhole, ChartNoAxesCombined, Settings2, Sparkles, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
const links = [ ['/', 'Today', House], ['/sell', 'Sell', ShoppingBag], ['/buy', 'Buy', Truck], ['/stock', 'Stock', Package], ['/money', 'Money', Wallet], ['/close', 'Close', LockKeyhole], ['/reports', 'Reports', ChartNoAxesCombined], ['/setup', 'Setup', Settings2] ] as const;
export function Navigation() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  return <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`}><Link href="/" className="brand" aria-label="Little Spell home"><span className="brand-mark"><Sparkles size={20} /></span>{!collapsed && <span className="brand-name">little spell<span className="brand-tagline">YOUR BUSINESS, SIMPLER</span></span>}</Link><nav id="main-navigation" aria-label="Main navigation">{links.map(([href, label, Icon]) => <Link key={href} href={href} className={`nav-item ${(pathname === href || href !== '/' && pathname.startsWith(`${href}/`)) ? 'active' : ''}`} aria-label={label} aria-current={(pathname === href || href !== '/' && pathname.startsWith(`${href}/`)) ? 'page' : undefined} title={label}><Icon size={19} />{!collapsed && <span className="nav-label">{label}</span>}</Link>)}</nav><button type="button" aria-label={collapsed ? "Expand navigation" : "Collapse navigation"} aria-expanded={!collapsed} className="icon-button nav-collapse" style={{ marginTop:36 }} onClick={() => setCollapsed(!collapsed)}>{collapsed ? <PanelLeftOpen size={19} /> : <PanelLeftClose size={19} />}</button><div className="sidebar-footer">A little clarity,<br/>every day.</div></aside>;
}
