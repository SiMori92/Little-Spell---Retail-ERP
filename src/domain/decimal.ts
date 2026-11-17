import Decimal from 'decimal.js';
export default Decimal.clone({ precision: 40, rounding: Decimal.ROUND_HALF_UP });
