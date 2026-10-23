let fieldSequence = 0;

/** Generates a document-unique id for a form control and its descriptions. */
export function createFieldId(prefix: string): string {
  fieldSequence += 1;
  return `${prefix}-${fieldSequence}`;
}
