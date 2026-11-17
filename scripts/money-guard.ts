import 'server-only';
import ts from 'typescript';
import { pathToFileURL } from 'node:url';

export function checkMoney(program: ts.Program): string[] {
  const checker = program.getTypeChecker();
  const found: string[] = [];
  const moneyTyped = (node: ts.Node): boolean => /Money|\$brand/.test(checker.typeToString(checker.getTypeAtLocation(node)));
  for (const source of program.getSourceFiles()) {
    if (source.isDeclarationFile || !source.fileName.includes('/src/')) continue;
    function visit(node: ts.Node): void {
      const floatCall = ts.isCallExpression(node) && /^(?:parseFloat|Number|Number\.parseFloat)$/.test(node.expression.getText(source));
      const numericOperation = (ts.isBinaryExpression(node) && ['+', '-', '*', '/', '%', '**'].includes(node.operatorToken.getText(source)) && (moneyTyped(node.left) || moneyTyped(node.right))) || (ts.isPrefixUnaryExpression(node) && (node.operator === ts.SyntaxKind.PlusToken || node.operator === ts.SyntaxKind.MinusToken) && moneyTyped(node.operand));
      if (floatCall || numericOperation) found.push(`${source.fileName}:${source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1}: Use exact decimal operations for money.`);
      ts.forEachChild(node, visit);
    }
    visit(source);
  }
  return found;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const config = ts.readConfigFile('tsconfig.json', ts.sys.readFile);
  const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, process.cwd());
  const errors = checkMoney(ts.createProgram(parsed.fileNames, parsed.options));
  for (const error of errors) console.error(error);
  process.exitCode = errors.length ? 1 : 0;
}
