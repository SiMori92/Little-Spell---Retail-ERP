const emailPattern = /[^\s@]{1,64}@[^\s@.]{1,253}\.[^\s@]{1,63}/;
const streetPattern = /\b(?:Road|Rd|Street|St|Lane|Ln|Ave)\b|[號路街巷]/i;
export function containsContactDetails(value: string): boolean {
  return value.includes('@') && (emailPattern.test(value) || /(^|\s)@\w/.test(value)) || /\d{3,}/.test(value) && streetPattern.test(value);
}
