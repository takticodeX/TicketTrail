import type { FieldValues, Path, UseFormSetError } from 'react-hook-form';

import { ApiError } from './client';

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return 'Could not reach the server. Try again.';
}

/** The first field message of a 422, without Pydantic's "Value error, " prefix. */
export function firstFieldMessage(error: unknown): string {
  if (error instanceof ApiError && error.code === 'validation_error') {
    const [first] = fieldErrors(error);
    if (first) return first.msg.replace(/^Value error, /, '');
  }
  return errorMessage(error);
}

/** Deleting a connection a project still uses names those projects. */
export function deleteErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.code === 'connection_in_use') {
    const projects = error.details.projects;
    if (Array.isArray(projects) && projects.length > 0) {
      return `${error.message} Used by: ${projects.join(', ')}.`;
    }
  }
  return errorMessage(error);
}

interface ServerFieldError {
  loc: (string | number)[];
  msg: string;
}

function fieldErrors(error: ApiError): ServerFieldError[] {
  const errors = error.details.errors;
  if (!Array.isArray(errors)) return [];
  return errors.filter(
    (e): e is ServerFieldError =>
      typeof e === 'object' && e !== null && Array.isArray(e.loc) && typeof e.msg === 'string',
  );
}

/**
 * Show a 422 from the API next to the form fields it is about. `fields` maps API
 * field names to form field names. Returns the message for errors that matched
 * no field, or null when every error was placed.
 */
export function applyServerErrors<T extends FieldValues>(
  error: unknown,
  setError: UseFormSetError<T>,
  fields: Record<string, Path<T>>,
): string | null {
  if (!(error instanceof ApiError)) return errorMessage(error);
  if (error.code !== 'validation_error') return error.message;
  const unplaced: string[] = [];
  for (const { loc, msg } of fieldErrors(error)) {
    const name = String(loc[1] ?? '');
    const field = fields[name];
    const text = msg.replace(/^Value error, /, '');
    if (field) setError(field, { message: text });
    else unplaced.push(text);
  }
  return unplaced.length > 0 ? unplaced.join(' ') : null;
}
