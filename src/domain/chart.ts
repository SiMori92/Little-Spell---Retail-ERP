import snapshot from '../../seed/coa_snapshot.json';
import addenda from '../../seed/coa_addenda.json';
export const approvedChartRows=[...snapshot.rows,...addenda.rows];
