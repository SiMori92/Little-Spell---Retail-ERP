import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import type { ButtonHTMLAttributes } from 'react';
const variants = cva('button', { variants: { variant: { default: '', secondary: 'secondary', ghost: 'ghost', danger: 'danger' } }, defaultVariants: { variant: 'default' } });
export function Button({ asChild = false, variant, className, type = 'button', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof variants> & { asChild?: boolean }) {
  const Component = asChild ? Slot : 'button';
  return <Component {...(!asChild ? { type } : {})} className={variants({ variant, className })} {...props} />;
}
