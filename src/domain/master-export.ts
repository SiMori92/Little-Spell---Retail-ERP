import { masterHeaders } from './master-csv';
import type { MasterProjection } from './schemas/masters';
import { serializeCsv } from './csv';

export function exportMasters(area: 'suppliers' | 'products' | 'channels' | 'accounts', projection: MasterProjection, keys?: ReadonlySet<string>): string {
  let rows: unknown[][];
  if (area === 'suppliers') rows = projection.suppliers.filter((item) => !keys || keys.has(item.record.supplierRef)).map(({record}) => [record.supplierRef,record.legalName,record.country,record.currency,record.defaultIncoterm,record.paymentTerms,record.canInvoiceToTaxId,record.declarationRef,record.evidenceRef]);
  else if (area === 'products') rows = projection.products.filter((item) => !keys || keys.has(item.record.sku)).map(({record}) => [record.sku,record.name,record.piecesPerSaleUnit,record.supplierRef,record.ingredientRef,record.evidenceRef,record.productType]);
  else if (area === 'channels') rows = projection.channels.filter((item) => !keys || keys.has(item.record.code)).map(({record}) => [record.code,record.name]);
  else rows = projection.accounts.filter((item) => !keys || keys.has(item.record.code)).map(({record}) => [record.code,record.nameEn,record.nameZh,record.type,record.statement,record.normalBalance,record.statutoryCode,record.taxTreatment,record.taxRegime,record.subledger,record.isReserved,record.isContra,record.isClosingOnly,record.activeFrom,record.activeTo]);
  return serializeCsv([masterHeaders[area].header,...rows]);
}
