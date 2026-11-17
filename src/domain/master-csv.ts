import { z } from 'zod';
import { DomainError } from './errors';
import { parseCsv } from './csv';
import suppliersHeader from '../../seed/schemas/suppliers_header_v1.json';
import productsHeader from '../../seed/schemas/products_header_v3.json';
import channelsHeader from '../../seed/schemas/channels_header_v1.json';
import accountsHeader from '../../seed/schemas/accounts_header_v1.json';
import { chartAccountSchema, channelSchema, productSchema, supplierSchema, masterAreaSchema } from './schemas/masters';
import { dateSchema, datasetSchema } from './schemas/primitives';
import { containsContactDetails } from './privacy';

export const masterHeaders = { suppliers:suppliersHeader, products:productsHeader, channels:channelsHeader, accounts:accountsHeader };
export function readMasterCsv(area: z.infer<typeof masterAreaSchema>, filename: string, csvText: string, dataset: z.infer<typeof datasetSchema>) {
  const expected = masterHeaders[area];
  const pattern = new RegExp(`^${dataset === 'SAMPLE' ? 'SAMPLE_' : ''}${area}_(\\d{4}-\\d{2}-\\d{2})\\.csv$`);
  const match = filename.match(pattern);
  if (!match || !dateSchema.safeParse(match[1]).success) throw new DomainError('filename', `Use a ${dataset === 'SAMPLE' ? 'SAMPLE_' : ''}${area}_YYYY-MM-DD.csv file for this dataset.`);
  if (!expected.verified) throw new DomainError('filename', 'This CSV contract has not been verified. Nothing can be imported.');
  const [header, ...rows] = parseCsv(csvText);
  if (!header || header.length !== expected.header.length || header.some((column, index) => column !== expected.header[index])) throw new DomainError('csvText', area === 'products' ? 'Use the exact product v3 header, including pieces_per_sale_unit and product_type. Older pack or product headers cannot be imported.' : 'The column names or their order do not match the supplied CSV template.');
  if (!rows.length) throw new DomainError('csvText', 'Add at least one record below the header.');
  return rows.map((cells, index) => {
    if (cells.length !== header.length) throw new DomainError('csvText', `Row ${index + 2} has the wrong number of cells.`);
    if (cells.some(containsContactDetails)) throw new DomainError('csvText', `Row ${index + 2} contains contact details. Keep personal data out of master files.`);
    const row = Object.fromEntries(header.map((column, offset) => [column, cells[offset]!.trim()]));
    try {
      if (area === 'suppliers') return supplierSchema.parse({ supplierRef:row.supplier_ref, legalName:row.legal_name, country:row.country, currency:row.currency, defaultIncoterm:row.default_incoterm, paymentTerms:row.payment_terms, canInvoiceToTaxId:row.can_invoice_to_tax_id, declarationRef:row.declaration_ref, evidenceRef:row.evidence_ref });
      if (area === 'products') {
        if (!/^[1-9]\d{0,9}$/.test(row.pieces_per_sale_unit ?? '')) throw new DomainError('csvText', `Row ${index + 2}: pieces per sale unit must be a positive whole number.`);
        return productSchema.parse({ sku:row.sku, name:row.name, uom:'PC', piecesPerSaleUnit:parseInt(row.pieces_per_sale_unit!,10), supplierRef:row.supplier_ref, ingredientRef:row.ingredient_ref, productType:row.product_type, evidenceRef:row.evidence_ref });
      }
      if (area === 'channels') return channelSchema.parse(row);
      const boolean = (key: string) => { if (row[key] !== 'true' && row[key] !== 'false') throw new DomainError('csvText', `Row ${index + 2}: use true or false in the flag columns.`); return row[key] === 'true'; };
      return chartAccountSchema.parse({ code:row.account_code, nameEn:row.account_name_en, nameZh:row.account_name_zh, type:row.type, statement:row.statement, normalBalance:row.normal_balance, statutoryCode:row.statutory_code, taxTreatment:row.tax_treatment || null, taxRegime:row.tax_regime, subledger:row.subledger, isReserved:boolean('is_reserved'), isContra:boolean('is_contra'), isClosingOnly:boolean('is_closing_only'), activeFrom:row.active_from || null, activeTo:row.active_to || null });
    } catch (error) {
      if (error instanceof DomainError) throw error;
      const field = error instanceof z.ZodError ? error.issues[0]?.path.map(String).join('.') : '';
      throw new DomainError('csvText', `Row ${index + 2}: check ${field || 'the values'} against the import guide. No submitted values were logged.`);
    }
  });
}
