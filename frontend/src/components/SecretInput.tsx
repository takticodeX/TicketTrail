import { PasswordInput, type PasswordInputProps } from '@mantine/core';
import { forwardRef } from 'react';

interface SecretInputProps extends PasswordInputProps {
  /** A secret is already stored: leaving the field empty keeps it. */
  saved: boolean;
}

/** Write-only secret field: shows "••••••• (saved)" once a value is stored. */
export const SecretInput = forwardRef<HTMLInputElement, SecretInputProps>(function SecretInput(
  { saved, description, ...props },
  ref,
) {
  return (
    <PasswordInput
      ref={ref}
      autoComplete="new-password"
      placeholder={saved ? '••••••• (saved)' : undefined}
      description={
        <>
          {description}
          {saved && <> Leave empty to keep the saved value.</>}
        </>
      }
      {...props}
    />
  );
});
