import Link from 'next/link';
import { Plus } from 'lucide-react';
export function QuickActions(){return <details className="quick-actions"><summary className="button"><Plus size={16}/> New</summary><nav aria-label="Quick actions" className="card">{[['/sell?action=etsy','Etsy import'],['/sell?action=deal','Instagram deal'],['/buy?action=po','Supplier order'],['/stock?action=count','Stock count'],['/money?action=expense','Expense'],['/money?action=owner','Owner funds']].map(([href,label])=><Link key={href} href={href!}>{label}</Link>)}</nav></details>;}
